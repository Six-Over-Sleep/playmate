"""개인별 인정 근거와 지급/회수 예약. 공개 승인 API나 별도 XP 원장은 만들지 않는다."""

from backend.app.domain.recruit_program import PolicyError


class RecruitRewardService:
    def __init__(self, program_service, policy=None):
        self.program_service = program_service
        self.repository = program_service.repository
        self.policy = policy

    def recognize(self, recruit_id, activity_id, member_id, kind):
        """확정된 외부 판정 정책만 신뢰해 한 사람의 인정과 지급 요청을 함께 저장한다."""
        if self.policy is None:
            raise PolicyError(
                "개인 참여/완료 인정 정책이 아직 연결되지 않았습니다.", 503
            )
        if not kind or len(kind) > 50:
            raise PolicyError("인정 종류는 1~50자여야 합니다.", 422)
        with self.program_service.transaction():
            self.repository.actor(member_id, lock=True)
            program = self.repository.load(recruit_id, lock=True)
            activity = self.repository.activity(activity_id)
            if activity is None or activity.recruit_id != recruit_id:
                raise PolicyError("모임 활동을 찾을 수 없습니다.", 404)
            if not any(
                item.member_id == member_id and item.status in {"ACCEPTED", "LEFT"}
                for item in program.applications
            ):
                raise PolicyError("참여 기록이 없는 회원을 인정할 수 없습니다.", 403)
            if (
                program.lifecycle_status in {"CANCELED", "ABORTED"}
                and "COMPLETION" in kind
            ):
                raise PolicyError("취소/중도 종료는 정상 완료로 인정할 수 없습니다.")
            decision = self.policy.evaluate(activity, member_id, kind)
            if not decision.approved:
                raise PolicyError("활동 인정 조건을 충족하지 않았습니다.")
            if not all(
                [decision.policy_version, decision.evidence, decision.scope_key]
            ):
                raise PolicyError("판정 정책·근거·한도 범위가 필요합니다.", 503)
            key = f"activity:{activity_id}:member:{member_id}:kind:{kind}"
            previous = self.repository.recognition(key)
            if previous:
                if previous.payload["status"] == "INVALIDATED":
                    raise PolicyError(
                        "재인정은 원 회수 참조를 포함한 공통 정책 확정 후 지원합니다."
                    )
                return previous.payload
            payload = {
                "recognition_key": key,
                "activity_id": activity_id,
                "member_id": member_id,
                "recruit_id": recruit_id,
                "recognition_kind": kind,
                "status": "APPROVED",
                "reward_status": "PENDING",
                "policy_version": decision.policy_version,
                "evidence": decision.evidence,
                "scope_key": decision.scope_key,
                "recognized_at": self.program_service.clock().isoformat(),
                "week": activity.payload.get("week"),
                "submission_stage": activity.payload.get("submission_stage"),
            }
            self.repository.save_recognition(
                key, recruit_id, member_id, activity_id, payload
            )
            self.repository.enqueue(recruit_id, "XP_GRANT", f"grant:{key}", payload)
            return payload

    def invalidate(self, recruit_id, recognition_key, reason):
        """권한 있는 판정 시스템이 호출할 내부 함수. 지정한 원 지급만 회수 대상으로 삼는다."""
        if self.policy is None:
            raise PolicyError("인정/무효 정책 연결이 필요합니다.", 503)
        if not reason.strip():
            raise PolicyError("무효 사유가 필요합니다.", 422)
        with self.program_service.transaction():
            self.repository.load(recruit_id, lock=True)
            record = self.repository.recognition(recognition_key)
            if record is None or record.recruit_id != recruit_id:
                raise PolicyError("개인 인정 기록을 찾을 수 없습니다.", 404)
            payload = dict(record.payload)
            payload["status"] = "INVALIDATED"
            record.payload = payload
            self.repository.enqueue(
                recruit_id,
                "XP_REVOKE",
                f"revoke:{recognition_key}",
                {
                    "member_id": record.member_id,
                    "reason": reason,
                    "original_event_key": (
                        f"recruit:{recruit_id}:grant:{recognition_key}"
                    ),
                },
            )


class RecruitOutboxService:
    def __init__(self, program_service, gateways=None):
        self.program_service = program_service
        self.repository = program_service.repository
        self.gateways = gateways or {}

    def dispatch(self):
        """다중 worker의 같은 요청 처리를 직렬화하고 실패해도 다음 실행에서 재시도한다.

        외부 성공 직후 DB 저장이 실패할 수 있으므로 수신 측 event_key 중복 방지가 필수다.
        어댑터가 없는 사건은 대기로 남기며 전달 완료라고 표시하지 않는다.
        """
        if not self.gateways:
            return 0
        events = self.repository.pending_events(set(self.gateways))
        self.repository.session.rollback()
        delivered = 0
        for key, recruit_id in events:
            with self.program_service.transaction():
                # 모임 변경과 동일하게 모임 → outbox 순서로 잠가 교착을 피한다.
                program = self.repository.load(recruit_id, lock=True)
                event = self.repository.lock_event(key)
                if event is None or event.status != "PENDING":
                    continue
                if (
                    event.schedule_version is not None
                    and event.schedule_version != program.schedule_version
                ):
                    event.status = "SUPERSEDED"
                    continue
                if event.kind == "DISCORD_PREPARE" and (
                    program.lifecycle_status in {"CANCELED", "ABORTED", "COMPLETED"}
                    or self.program_service.clock() >= program.starts_at
                ):
                    event.status = "SUPERSEDED"
                    continue
                payload = dict(event.payload)
                if event.kind == "DISCORD_PREPARE":
                    payload["member_ids"] = [
                        item.member_id for item in program.accepted()
                    ]
                if event.kind == "XP_REVOKE":
                    original = self.repository.event(payload["original_event_key"])
                    if original is None or original.status != "SENT":
                        continue
                    payload["original_grant_reference"] = original.payload[
                        "external_reference"
                    ]
                gateway = self.gateways.get(event.kind)
                if gateway is None:
                    continue
                event.attempts += 1
                try:
                    reference = gateway.deliver(key, event.kind, payload)
                    if not isinstance(reference, str) or not reference.strip():
                        raise ValueError("외부 확정 참조 누락")
                except Exception as error:
                    # 예외 본문에는 토큰·요청 본문이 포함될 수 있어 종류만 저장한다.
                    event.payload = {
                        **event.payload,
                        "last_error_type": type(error).__name__,
                    }
                    continue
                event.status = "SENT"
                event.payload = {**event.payload, "external_reference": reference}
                self.repository.reward_delivered(event, payload, reference)
                delivered += 1
        return delivered
