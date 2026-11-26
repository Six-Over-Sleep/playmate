"""프로젝트·스터디 유스케이스. ORM과 외부 구현 대신 저장소·계약을 주입한다."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo
from typing import Protocol

from backend.app.domain.recruit_program import PolicyError, Program
from backend.app.schemas.recruit_program import ProgramCreate
from backend.app.services.recruit_program_presenter import program_view


class SkillCatalog(Protocol):
    """공통 기술 사전 담당자가 제공할 조회 계약. 이름만으로 검증했다고 처리하지 않는다."""

    def validate(self, skill_ids: list[int]) -> None: ...

    def names(self, skill_ids: list[int]) -> dict[str, str]: ...


class UnavailableSkillCatalog:
    def validate(self, skill_ids):
        raise PolicyError("공통 기술 사전 연결이 필요합니다.", 503)


class ProgramService:
    def __init__(self, repository, catalog=None, clock=None, curriculum_policy=None):
        self.repository = repository
        self.catalog = catalog if catalog is not None else UnavailableSkillCatalog()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.curriculum_policy = curriculum_policy

    @contextmanager
    def transaction(self):
        """업무 결과와 outbox가 함께 확정되도록 실패 시 전부 되돌린다."""
        try:
            yield
            self.repository.session.commit()
        except Exception:
            self.repository.session.rollback()
            raise

    def create(self, member_id, data, *, existing_recruit_id=None):
        """서버 권한으로 생성 주체를 판단하고 일정·개설자 신청·메타데이터를 원자 저장한다."""
        with self.transaction():
            admin = self.repository.actor(member_id, lock=True)
            now = self.clock()
            program = Program(
                category=data.category,
                creator_id=member_id,
                creator_type="ADMIN" if admin else "USER",
                capacity=data.capacity,
                starts_at=data.starts_at,
                ends_at=data.ends_at,
                required_skill_ids=data.required_skill_ids,
            )
            if not program.is_recruiting(now):
                raise PolicyError("시작 24시간 이전에 모임을 생성해주세요.", 422)
            if data.category == "project":
                self.catalog.validate(data.required_skill_ids)
            if not admin:
                if data.category == "project" and data.creator_application is None:
                    raise PolicyError(
                        "사용자 개설자의 담당 기술 신청이 필요합니다.", 422
                    )
                application = data.creator_application
                program.apply(
                    member_id,
                    now,
                    skill_ids=application.skill_ids if application else [],
                    direct_input=(
                        application.direct_input.model_dump(mode="json")
                        if application
                        else {}
                    ),
                    leader_volunteer=(
                        application.leader_volunteer if application else False
                    ),
                    restricted=self.repository.restricted(member_id),
                    creator=True,
                )
            elif data.creator_application is not None:
                raise PolicyError("관리자 생성은 자동 참여하지 않습니다.", 422)
            if existing_recruit_id is not None:
                self.repository.reset_configuration(existing_recruit_id)
            result = self.repository.create(program, data, now, existing_recruit_id)
            # 종류·난이도는 DB 전용 모델을 추가 복제하지 않고 프로그램 메타데이터로 보존한다.
            self.repository.set_metadata(
                program.recruit_id,
                {
                    "study_type": data.study_type,
                    "difficulty": data.difficulty,
                    "study_topic": data.study_topic,
                    "study_period": data.study_period,
                    "study_method": data.study_method,
                    "regular_days": data.regular_days,
                    "regular_time": (
                        data.regular_time.isoformat() if data.regular_time else None
                    ),
                    "regular_start_date": (
                        data.regular_start_date.isoformat()
                        if data.regular_start_date
                        else None
                    ),
                    "required_skill_names": (
                        self.catalog.names(data.required_skill_ids)
                        if data.category == "project"
                        else {}
                    ),
                },
            )
            return result

    def detail(self, recruit_id, member_id):
        """공개 상세를 반환하고 로그인 회원에게만 본인 신청 상태와 서버 권한을 추가한다."""
        if member_id is not None:
            self.repository.actor(member_id)
        bundle = self.repository.detail_bundle(recruit_id, member_id)
        program = bundle["program"]
        result = program_view(
            program,
            member_id,
            bundle["basic"],
            bundle["details"],
            bundle["eligibility"],
            self.clock(),
            self.curriculum_policy,
            {
                "waiting_count": bundle["counts"]["waiting"],
                "other_application_history": bundle["other_application_history"],
            },
        )
        result["members"] = self.member_views(
            program.creator_type,
            program.creator_id,
            program.leader_id,
            bundle["members"],
        )
        result["participation"] = self.participation_view(recruit_id, bundle["counts"])
        return result

    def members(self, recruit_id, member_id):
        """확정 참여자만 반환한다. 신청서·대기자 비공개 자료는 전달하지 않는다."""
        if member_id is not None:
            self.repository.actor(member_id)
        program, members = self.repository.participant_roster(recruit_id)
        return self.member_views(
            program["creator_type"],
            program["creator_id"],
            program["leader_id"],
            members,
        )

    @staticmethod
    def member_views(creator_type, creator_id, leader_id, members):
        """독립 API와 통합 상세에서 개설자/팀장 표시 규칙을 공유한다."""
        return [
            {
                **item,
                "role": (
                    "HOST"
                    if creator_type == "USER" and item["member_id"] == creator_id
                    else "MEMBER"
                ),
                "is_leader": item["member_id"] == leader_id,
            }
            for item in members
        ]

    def count(self, recruit_id, member_id):
        """기존 count 응답을 유지하면서 확정/대기 인원을 분리한다."""
        if member_id is not None:
            self.repository.actor(member_id)
        counts = self.repository.participation_counts(recruit_id)
        return self.participation_view(recruit_id, counts)

    @staticmethod
    def participation_view(recruit_id, counts):
        """통합/독립 응답에서 정원·빈자리 계산을 동일하게 유지한다."""
        count = counts["accepted"]
        return {
            "recruit_id": recruit_id,
            "current_members": count,
            "capacity": counts["capacity"],
            "remaining": max(0, counts["capacity"] - count),
            "waiting_count": counts["waiting"],
        }

    def list(self, member_id, category=None, base_rows=None):
        """기존 목록/집계를 재사용하고 민감한 신청 내용 없이 요약 응답을 만든다."""
        if category not in {None, "project", "study"}:
            raise PolicyError("신규 모임 목록은 프로젝트·스터디만 지원합니다.", 422)
        records = (
            self.repository.list_programs(base_rows, member_id)
            if base_rows is not None else self.repository.list_bundle(member_id, category)
        )
        return self.list_views(records, member_id, include_legacy=False)

    def mixed_list(self, member_id, category=None):
        """단일 목록 조회의 기존 모임과 신규 프로그램을 같은 배열로 반환한다."""
        return self.list_views(
            self.repository.list_bundle(member_id, category), member_id,
            include_legacy=True,
        )

    def list_views(self, records, member_id, *, include_legacy):
        """이미 읽은 데이터만 표시 형식으로 변환하며 DB를 다시 조회하지 않는다."""
        if not records:
            return []
        now = self.clock()
        return [
            program_view(
                program,
                member_id,
                basic,
                details,
                counts["eligibility"],
                now,
                self.curriculum_policy,
                counts,
            ) if program is not None else basic
            for program, basic, details, counts in records
            if program is not None or include_legacy
        ]

    def view(self, program, member_id):
        """상세에 필요한 부가 정보를 읽고 공통 직렬화 함수에 전달한다."""
        _, basic, details = self.repository.detail_context(program.recruit_id)
        basic.update(
            self.repository.social_summaries([program.recruit_id], member_id)[
                program.recruit_id
            ]
        )
        return program_view(
            program,
            member_id,
            basic,
            details,
            self.repository.eligibility_info(member_id),
            self.clock(),
            self.curriculum_policy,
        )

    @staticmethod
    def application_view(item):
        """본인의 접수 결과를 JSON용으로 변환한다. 시각은 시간대 포함 문자열로 유지한다."""
        values = asdict(item)
        for key in ("submitted_at", "changed_at"):
            values[key] = values[key].isoformat() if values[key] else None
        return values

    def apply(self, recruit_id, member_id, data):
        """회원·모임 잠금 후 신규 제한과 대기 순서를 검사해 접수 결과를 확정한다."""
        with self.transaction():
            self.repository.actor(member_id, lock=True)
            program = self.repository.load(recruit_id, lock=True)
            item = program.apply(
                member_id,
                self.clock(),
                skill_ids=data.skill_ids,
                direct_input=data.direct_input.model_dump(mode="json"),
                leader_volunteer=data.leader_volunteer,
                restricted=self.repository.restricted(member_id),
            )
            self.repository.save(program)
            return {
                **self.application_view(item),
                "application_status": item.status,
                "recruit_id": recruit_id,
                "participant_count": len(program.accepted()),
                "waiting_count": len(program.waiting()),
                "missing_skill_ids": program.missing(),
                "lifecycle_status": program.lifecycle_status,
                "message": (
                    "모임 참여가 확정되었습니다."
                    if item.status == "ACCEPTED"
                    else "대기 신청되었습니다."
                ),
                "reason_code": (
                    "CONDITIONS_MET"
                    if item.status == "ACCEPTED"
                    else (
                        "CAPACITY_FULL"
                        if len(program.accepted()) >= program.capacity
                        else "SKILL_SLOTS_RESERVED"
                    )
                ),
            }

    def cancel_application(self, recruit_id, member_id):
        """현재 생애주기를 먼저 적용하고 취소/이탈·승격·이탈 누적을 함께 저장한다."""
        with self.transaction():
            # 회원 → 모임 잠금 순서를 모든 회원 변경 경로에서 통일한다.
            self.repository.actor(member_id, lock=True)
            program = self.repository.load(recruit_id, lock=True)
            now = self.clock()
            program.tick(now)
            departure, item = program.cancel_application(member_id, now)
            if departure:
                self.repository.record_departure(program, member_id, item, now)
            self.repository.save(program)
            return {
                **self.application_view(item),
                "message": "모임 참여 취소 완료",
                "recruit_id": recruit_id,
                "application_status": item.status,
                "participant_count": len(program.accepted()),
                "waiting_count": len(program.waiting()),
                "lifecycle_status": program.lifecycle_status,
            }

    def decide(self, recruit_id, member_id, action, data):
        """선정 팀장의 일정 결정만 처리한다. 연장은 요청 키·본문을 함께 비교해 재시도한다."""
        with self.transaction():
            self.repository.actor(member_id, lock=True)
            program = self.repository.load(recruit_id, lock=True)
            now = self.clock()
            if action == "extend":
                body = data.model_dump(mode="json")
                previous = self.repository.command(recruit_id, data.request_key)
                if previous:
                    if previous.member_id != member_id or previous.request != body:
                        raise PolicyError(
                            "같은 요청 키를 다른 내용으로 재사용할 수 없습니다."
                        )
                    return previous.response
            program.tick(now)
            if action == "extend":
                program.extend(
                    member_id, now, data.starts_at, data.ends_at, data.schedule_version
                )
                metadata = dict(self.repository.metadata(recruit_id))
                if metadata.get("regular_start_date"):
                    local = program.starts_at.astimezone(ZoneInfo("Asia/Seoul"))
                    metadata["regular_start_date"] = local.date().isoformat()
                    metadata["regular_time"] = (
                        local.time().replace(tzinfo=None).isoformat()
                    )
                    self.repository.set_metadata(recruit_id, metadata)
            elif action == "exception-start":
                program.choose_exception(member_id, now, data.schedule_version)
            elif action == "cancel":
                program.cancel(member_id, now, data.reason)
            elif action == "abort":
                program.end_early(member_id, now, data.reason)
            else:
                raise PolicyError("지원하지 않는 결정입니다.", 422)
            self.repository.save(program)
            result = self.view(program, member_id)
            if action == "extend":
                self.repository.store_command(
                    recruit_id, member_id, data.request_key, body, result
                )
            return result

    def edit(self, recruit_id, member_id, data):
        """개설자의 부분 수정을 병합 검증한다. 타인 첫 신청 이후 핵심 조건 변경은 거절한다."""
        with self.transaction():
            self.repository.actor(member_id, lock=True)
            program = self.repository.load(recruit_id, lock=True)
            if not program.permissions(member_id, self.clock())["can_edit"]:
                raise PolicyError("모집 중인 모임 개설자만 수정할 수 있습니다.", 403)
            changes = data.model_dump(exclude_unset=True)
            schedule_fields = {
                "recruit_mode", "regular_days", "regular_time",
                "regular_start_date", "meeting_start", "meeting_end",
            }
            if schedule_fields.intersection(changes):
                return self.edit_configuration(program, member_id, changes)
            core = {
                key: changes.pop(key)
                for key in list(changes)
                if key in {"capacity", "starts_at", "ends_at", "required_skill_ids"}
            }
            if core:
                if not program.is_recruiting(self.clock()):
                    raise PolicyError(
                        "마감 이후 일정 변경은 정식 연장 절차를 사용해주세요."
                    )
                if program.extension_count and {"starts_at", "ends_at"}.intersection(
                    core
                ):
                    raise PolicyError(
                        "연장 이후 일정을 일반 수정으로 우회할 수 없습니다."
                    )
                if any(
                    item.member_id != program.creator_id
                    for item in program.applications
                ):
                    raise PolicyError(
                        "다른 회원이 신청한 이후 핵심 모집 조건은 변경할 수 없습니다."
                    )
                if any(value is None for value in core.values()):
                    raise PolicyError("핵심 조건을 null로 변경할 수 없습니다.", 422)
                merged = {
                    "category": program.category,
                    "creator_id": program.creator_id,
                    "creator_type": program.creator_type,
                    "capacity": program.capacity,
                    "starts_at": program.starts_at,
                    "ends_at": program.ends_at,
                    "required_skill_ids": program.required_skill_ids,
                    **core,
                }
                checked = Program(**merged)
                if not checked.is_recruiting(self.clock()):
                    raise PolicyError("새 모집 마감은 미래여야 합니다.", 422)
                if checked.category == "project":
                    self.catalog.validate(checked.required_skill_ids)
                    covered = {
                        skill for item in program.accepted() for skill in item.skill_ids
                    }
                    if not covered.issubset(checked.required_skill_ids):
                        raise PolicyError(
                            "개설자의 담당 기술을 제거할 수 없습니다.", 422
                        )
                elif checked.required_skill_ids:
                    raise PolicyError("스터디는 필수 기술을 사용하지 않습니다.", 422)
                for key in core:
                    setattr(program, key, getattr(checked, key))
                if "required_skill_ids" in core:
                    metadata = dict(self.repository.metadata(recruit_id))
                    metadata["required_skill_names"] = self.catalog.names(
                        program.required_skill_ids
                    )
                    self.repository.set_metadata(recruit_id, metadata)
                if "starts_at" in core:
                    metadata = dict(self.repository.metadata(recruit_id))
                    basic = self.repository.basic_detail(recruit_id)
                    if basic["recruit_mode"] == "regular":
                        local = program.starts_at.astimezone(ZoneInfo("Asia/Seoul"))
                        metadata["regular_start_date"] = local.date().isoformat()
                        metadata["regular_time"] = local.time().replace(tzinfo=None).isoformat()
                        day = ["월", "화", "수", "목", "금", "토", "일"][local.weekday()]
                        if day not in (metadata.get("regular_days") or []):
                            raise PolicyError("시작 날짜의 요일이 모임 요일에 포함되어야 합니다.", 422)
                        self.repository.set_metadata(recruit_id, metadata)
                program.schedule_version += 1
                program.refresh_readiness()
                self.repository.save(program)
            self.repository.edit(program, changes, self.clock())
            return self.view(program, member_id)

    def edit_configuration(self, program, member_id, changes):
        """종류별 필수 일정을 생성 계약으로 재검증하고 같은 모임에 반영한다."""
        if not program.is_recruiting(self.clock()) or any(
            item.member_id != program.creator_id for item in program.applications
        ):
            raise PolicyError("다른 회원 신청 이력이 없고 모집 마감 전일 때만 변경할 수 있습니다.")
        if program.extension_count:
            raise PolicyError("연장 이후 일정은 정식 연장 절차를 사용해주세요.")
        basic = self.repository.basic_detail(program.recruit_id)
        metadata = dict(self.repository.metadata(program.recruit_id))
        values = {
            key: value for key, value in {**basic, **metadata}.items()
            if key in ProgramCreate.model_fields
        }
        values.update(
            category=program.category, capacity=program.capacity,
            starts_at=program.starts_at, ends_at=program.ends_at,
            required_skill_ids=program.required_skill_ids,
        )
        values.update(changes)
        if values["recruit_mode"] == "regular":
            values.update(meeting_start=None, meeting_end=None)
        else:
            values.update(regular_days=None, regular_time=None, regular_start_date=None)
        checked = ProgramCreate.model_validate(values)
        if self.clock() >= checked.starts_at - timedelta(hours=24):
            raise PolicyError("새 모집 마감은 미래여야 합니다.", 422)
        if checked.category == "project":
            self.catalog.validate(checked.required_skill_ids)
            covered = {skill for item in program.accepted() for skill in item.skill_ids}
            if not covered.issubset(checked.required_skill_ids):
                raise PolicyError("개설자의 담당 기술을 제거할 수 없습니다.", 422)
        if checked.recruit_mode == "regular":
            local = checked.starts_at.astimezone(ZoneInfo("Asia/Seoul"))
            day = ["월", "화", "수", "목", "금", "토", "일"][local.weekday()]
            if day not in checked.regular_days:
                raise PolicyError("시작 날짜의 요일이 모임 요일에 포함되어야 합니다.", 422)
        program.starts_at, program.ends_at = checked.starts_at, checked.ends_at
        program.capacity = checked.capacity
        program.required_skill_ids = checked.required_skill_ids
        program.schedule_version += 1
        program.refresh_readiness()
        self.repository.configure_schedule(program.recruit_id, checked)
        if checked.category == "project":
            metadata = dict(self.repository.metadata(program.recruit_id))
            metadata["required_skill_names"] = self.catalog.names(checked.required_skill_ids)
            self.repository.set_metadata(program.recruit_id, metadata)
        self.repository.save(program)
        self.repository.edit(
            program,
            {key: value for key, value in changes.items()
             if key in {"title", "body", "contact_method"}},
            self.clock(),
        )
        return self.view(program, member_id)

    def archive(self, recruit_id, member_id):
        """다른 회원 신청 전의 초안만 개설자가 논리 삭제한다. 단체 취소와 혼용하지 않는다."""
        with self.transaction():
            self.repository.actor(member_id, lock=True)
            program = self.repository.load(recruit_id, lock=True)
            if program.creator_id != member_id:
                raise PolicyError("모임 개설자만 삭제할 수 있습니다.", 403)
            if not program.is_recruiting(self.clock()) or any(
                item.member_id != member_id for item in program.applications
            ):
                raise PolicyError(
                    "참여 이력이 있는 모임은 삭제 대신 취소/종료 절차를 사용해주세요."
                )
            self.repository.archive(recruit_id, self.clock())
            return {"message": "모임 삭제 완료"}

    def curriculum(self, recruit_id, member_id, data=None):
        """스터디 초안을 조회하거나 개설자·편집 기간·버전을 검사해 저장한다."""
        with self.transaction():
            self.repository.actor(member_id, lock=data is not None)
            program = self.repository.load(recruit_id, lock=data is not None)
            if program.category != "study":
                raise PolicyError("스터디 커리큘럼만 지원합니다.", 422)
            if data is None:
                return self.repository.curriculum(recruit_id)
            if not program.permissions(member_id, self.clock())["can_edit_curriculum"]:
                raise PolicyError(
                    "현재 사용자 개설 스터디의 개설자만 수정할 수 있습니다.", 403
                )
            if self.curriculum_policy is not None and not self.curriculum_policy(
                program, self.clock()
            ):
                raise PolicyError("현재 커리큘럼 편집 가능 기간이 아닙니다.")
            return self.repository.save_curriculum(
                recruit_id, data.version, [item.model_dump() for item in data.items]
            )

    def activities(self, recruit_id, member_id, data=None):
        """확정 참여자의 주간 인증·결과물·후기를 저장한다. 개인 인정/XP 지급과는 분리한다."""
        with self.transaction():
            self.repository.actor(member_id, lock=data is not None)
            program = self.repository.load(recruit_id, lock=data is not None)
            if data is None:
                return self.repository.activities(recruit_id)
            now = self.clock()
            program.tick(now)
            item = program.active_application(member_id)
            if item is None or item.status != "ACCEPTED":
                raise PolicyError("확정 참여자만 활동을 기록할 수 있습니다.", 403)
            if data.activity_type == "REVIEW":
                if program.lifecycle_status != "COMPLETED":
                    raise PolicyError("정상 운영 종료 후 후기를 작성해주세요.")
            elif program.lifecycle_status != "IN_PROGRESS":
                raise PolicyError("진행 중인 모임에서 활동을 등록해주세요.")
            if data.activity_type == "WEEKLY_CHECK" and program.category != "study":
                raise PolicyError("주간 인증은 스터디 기능입니다.", 422)
            if (
                data.activity_type == "OUTPUT"
                and program.category == "project"
                and data.submission_stage is None
            ):
                raise PolicyError("프로젝트 결과물은 중간/최종 구분이 필요합니다.", 422)
            self.repository.save(program)
            return self.repository.add_activity(
                recruit_id, member_id, data.model_dump(mode="json"), now
            )

    def tick(self, on_error=None):
        """모임별로 확정/롤백한다. 오류 통지는 예약 실행기가 재시도 주기를 고를 때 쓴다."""
        ids = self.repository.pending_ids(self.clock())
        self.repository.session.rollback()
        processed = 0
        for recruit_id in ids:
            try:
                with self.transaction():
                    # 조회 후 일정 연장/취소가 발생할 수 있어 잠금 뒤 최신 상태를 읽는다.
                    program = self.repository.load(recruit_id, lock=True)
                    program.tick(self.clock())
                    self.repository.save(program)
                processed += 1
            except Exception as error:
                # DB 예외 본문에는 접속 정보나 개인 자료가 포함될 수 있다.
                logging.getLogger(__name__).error(
                    "모임 상태 변경 실패 recruit_id=%s error_type=%s",
                    recruit_id,
                    type(error).__name__,
                )
                if on_error is not None:
                    on_error(recruit_id)
        return processed
