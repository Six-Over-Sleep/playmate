"""프로젝트·스터디의 결정 규칙. DB·시스템 시계·외부 API에 의존하지 않는다."""

from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class PolicyError(ValueError):
    """API가 사용자에게 돌려줄 업무 오류와 HTTP 상태를 함께 보관한다."""

    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def aware(value):
    """시간대가 없는 신규 일정을 거부해 서버별 시각 해석 차이를 방지한다."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise PolicyError("시간대가 포함된 시각이 필요합니다.", 422)
    return value.astimezone(timezone.utc)


@dataclass
class Application:
    member_id: int
    sequence: int
    submitted_at: datetime
    skill_ids: list[int] = field(default_factory=list)
    direct_input: dict = field(default_factory=dict)
    leader_volunteer: bool = False
    status: str = "WAITING"
    application_id: int | None = None
    changed_at: datetime | None = None


@dataclass
class Program:
    """한 모임의 업무 상태. 저장/잠금은 Repository, 시간은 호출자가 제공한다."""

    category: str
    creator_id: int
    creator_type: str
    capacity: int
    starts_at: datetime
    ends_at: datetime
    required_skill_ids: list[int] = field(default_factory=list)
    recruit_id: int | None = None
    lifecycle_status: str = "RECRUITING"
    leader_id: int | None = None
    leader_selected: bool = False
    extension_count: int = 0
    schedule_version: int = 1
    exception_version: int | None = None
    exception_missing_skills: list[int] = field(default_factory=list)
    termination_reason: str | None = None
    applications: list[Application] = field(default_factory=list)
    application_changes: dict[int, Application] = field(
        default_factory=dict, repr=False, compare=False
    )
    leader_history: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    def __post_init__(self):
        """복원/생성 시 공통 일정·정원·필수 기술 불변 조건을 검사한다."""
        self.starts_at, self.ends_at = aware(self.starts_at), aware(self.ends_at)
        if self.category not in {"project", "study"}:
            raise PolicyError("프로젝트·스터디 전용 기능입니다.", 422)
        if self.creator_type not in {"USER", "ADMIN"}:
            raise PolicyError("생성 주체가 올바르지 않습니다.", 422)
        maximum = 4 if self.creator_type == "ADMIN" else 5
        if not 2 <= self.capacity <= maximum:
            raise PolicyError(f"모집 정원은 2명부터 {maximum}명까지입니다.", 422)
        if self.ends_at <= self.starts_at:
            raise PolicyError("종료는 시작 이후여야 합니다.", 422)
        if len(set(self.required_skill_ids)) != len(self.required_skill_ids):
            raise PolicyError("필수 기술이 중복되었습니다.", 422)
        if self.category == "project" and not self.required_skill_ids:
            raise PolicyError("프로젝트 필수 기술을 선택해주세요.", 422)

    @property
    def deadline_at(self):
        """현재 일정의 모집 마감을 계산해 연장 후 과거 마감을 재사용하지 않는다."""
        return self.starts_at - timedelta(hours=24)

    def accepted(self):
        """시작 조건과 정원 계산에 포함되는 현재 확정자만 반환한다."""
        return [item for item in self.applications if item.status == "ACCEPTED"]

    def waiting(self):
        """제출 시각이 같아도 모임별 순번으로 순서를 고정한다."""
        return sorted(
            (item for item in self.applications if item.status == "WAITING"),
            key=lambda item: (item.submitted_at, item.sequence),
        )

    def missing(self, extra_skills=(), members=None):
        """확정자 기술의 합집합을 사용해 한 사람의 다중 기술을 중복 인원 없이 반영한다."""
        covered = set(extra_skills)
        for item in self.accepted() if members is None else members:
            covered.update(item.skill_ids)
        return sorted(set(self.required_skill_ids) - covered)

    def active_application(self, member_id):
        """취소/이탈 이력과 현재 유효 신청을 구분해 재신청 검증에 사용한다."""
        return next(
            (
                item
                for item in self.applications
                if item.member_id == member_id
                and item.status in {"ACCEPTED", "WAITING"}
            ),
            None,
        )

    def is_recruiting(self, now):
        """준비 상태여도 모집 마감 시각부터는 신규 신청과 승격을 금지한다."""
        return (
            self.lifecycle_status in {"RECRUITING", "READY"}
            and aware(now) < self.deadline_at
        )

    def emit(self, kind, key, payload):
        """영속 outbox의 중복 방지 키를 만든다. 전달 성공으로 처리하지 않는다."""
        self.events.append(
            {
                "kind": kind,
                "key": key,
                "payload": payload,
                "schedule_version": self.schedule_version,
            }
        )

    def refresh_readiness(self, members=None):
        """최소 인원·기술 충족은 준비 상태만 바꾸며 예정일 전에 시작시키지 않는다."""
        if self.lifecycle_status in {"RECRUITING", "READY"}:
            members = self.accepted() if members is None else members
            self.lifecycle_status = (
                "READY"
                if len(members) >= 2 and not self.missing(members=members)
                else "RECRUITING"
            )

    def _can_accept(self, skill_ids):
        """신청자를 가정한 남은 자리로 미충족 기술 자리를 보수적으로 확보한다."""
        remaining = self.capacity - len(self.accepted()) - 1
        return remaining >= 0 and (
            self.category == "study" or remaining >= len(self.missing(skill_ids))
        )

    def apply(
        self,
        member_id,
        now,
        skill_ids=(),
        direct_input=None,
        leader_volunteer=False,
        restricted=False,
        creator=False,
    ):
        """신규 신청을 확정/대기로 배정한다. 제한 전의 기존 신청은 이 함수로 재접수하지 않는다."""
        now = aware(now)
        if not self.is_recruiting(now):
            raise PolicyError("모집이 마감되어 신청할 수 없습니다.")
        if restricted:
            raise PolicyError("중도이탈 누적 3회로 신규 모임 신청이 제한됩니다.", 403)
        if self.active_application(member_id):
            raise PolicyError("이미 접수된 신청입니다.")
        skills = sorted(set(skill_ids))
        if self.category == "project" and (
            not skills or not set(skills).issubset(self.required_skill_ids)
        ):
            raise PolicyError("프로젝트의 담당 기술을 1개 이상 선택해주세요.", 422)
        if self.category == "study" and skills:
            raise PolicyError("스터디는 담당 기술 신청서를 요구하지 않습니다.", 422)
        # 기존 대기자를 먼저 검토해 새 신청자의 순서 추월을 막는다.
        self.promote(now)
        item = Application(
            member_id=member_id,
            sequence=max((a.sequence for a in self.applications), default=0) + 1,
            submitted_at=now,
            skill_ids=skills,
            direct_input=deepcopy(direct_input or {}),
            leader_volunteer=leader_volunteer,
            changed_at=now,
        )
        if (creator or self._can_accept(skills)) and len(
            self.accepted()
        ) < self.capacity:
            item.status = "ACCEPTED"
        self.applications.append(item)
        self.application_changes[item.sequence] = item
        self.refresh_readiness()
        return item

    def promote(self, now):
        """스터디는 순서대로, 프로젝트는 자리 보존 조건에 맞는 대기자를 검토한다."""
        if not self.is_recruiting(now):
            return
        members = self.accepted()
        remaining = self.capacity - len(members)
        if remaining <= 0:
            self.refresh_readiness(members)
            return
        covered = {skill for member in members for skill in member.skill_ids}
        required = set(self.required_skill_ids)
        for item in self.waiting():
            missing = required - covered - set(item.skill_ids)
            if self.category == "study" or remaining - 1 >= len(missing):
                item.status, item.changed_at = "ACCEPTED", aware(now)
                self.application_changes[item.sequence] = item
                members.append(item)
                covered.update(item.skill_ids)
                remaining -= 1
                if remaining == 0:
                    break
        self.refresh_readiness(members)

    def select_leader(self, now, succession=False):
        """전날 최초 선정과 이탈 후 승계를 구분하고 역할 변경 이력을 남긴다."""
        if self.category != "project":
            return
        members = sorted(self.accepted(), key=lambda a: (a.submitted_at, a.sequence))
        if not succession and self.creator_type == "USER":
            volunteers = [item for item in members if item.leader_volunteer]
            members = volunteers or members
        selected = members[0].member_id if members else None
        if selected != self.leader_id:
            self.leader_history.append(
                {
                    "previous_id": self.leader_id,
                    "member_id": selected,
                    "at": aware(now).isoformat(),
                    "reason": "SUCCESSION" if succession else "INITIAL",
                }
            )
        self.leader_id, self.leader_selected = selected, True

    def cancel_application(self, member_id, now):
        """시작 전 취소와 시작 후 자발적 이탈을 구분한다. 반환값은 이탈 집계 대상 여부다."""
        now = aware(now)
        item = self.active_application(member_id)
        if item is None:
            raise PolicyError("유효한 신청이 없습니다.", 404)
        if self.lifecycle_status in {"COMPLETED", "CANCELED", "ABORTED"}:
            raise PolicyError("종료된 모임의 신청은 변경할 수 없습니다.")
        # 시작 작업이 늦었을 때 시작 전 취소처럼 처리하지 않는다.
        if now >= self.starts_at and self.lifecycle_status != "IN_PROGRESS":
            raise PolicyError(
                "시작 시각이 지났습니다. 모임 상태 처리 후 다시 시도해주세요."
            )
        departure = self.lifecycle_status == "IN_PROGRESS" and item.status == "ACCEPTED"
        item.status = "LEFT" if departure else "CANCELED"
        item.changed_at = now
        self.application_changes[item.sequence] = item
        if self.leader_selected and self.leader_id == member_id:
            self.select_leader(now, succession=True)
        self.promote(now)
        self.refresh_readiness()
        if now >= self.deadline_at:
            self.emit(
                "ROSTER_CHANGED",
                f"roster:{self.schedule_version}:{item.sequence}:{item.status}",
                {
                    "member_ids": [member.member_id for member in self.accepted()],
                    "leader_id": self.leader_id,
                },
            )
        return departure, item

    def require_leader_decision(self, member_id, now):
        """개설자와 팀장을 구분하고 마감 후~예정 시작 전의 결정 창을 검사한다."""
        now = aware(now)
        if self.category != "project" or self.leader_id != member_id:
            raise PolicyError("선정된 프로젝트 팀장만 처리할 수 있습니다.", 403)
        if not self.deadline_at <= now < self.starts_at:
            raise PolicyError("모집 마감 후 예정 시작 시각 전에 선택해주세요.")
        if self.lifecycle_status not in {"RECRUITING", "READY"}:
            raise PolicyError("현재 상태에서 결정할 수 없습니다.")

    def extend(self, member_id, now, starts_at, ends_at, expected_version):
        """달력 날짜·횟수·종료·버전을 검사하고 기존 신청을 보존한 채 일정을 갱신한다."""
        self.require_leader_decision(member_id, now)
        if self.schedule_version != expected_version:
            raise PolicyError("일정이 변경되었습니다. 최신 내용을 다시 확인해주세요.")
        if self.extension_count >= 2:
            raise PolicyError("프로젝트는 최대 2회까지 연장할 수 있습니다.")
        if len(self.accepted()) >= 2 and not self.missing():
            raise PolicyError(
                "시작 조건을 충족한 프로젝트는 미달 연장 대상이 아닙니다."
            )
        start, end, now = aware(starts_at), aware(ends_at), aware(now)
        seoul = ZoneInfo("Asia/Seoul")
        offset = (
            start.astimezone(seoul).date() - self.starts_at.astimezone(seoul).date()
        ).days
        if not 1 <= offset <= 14:
            raise PolicyError(
                "변경 전 시작일 다음 날부터 14일 이내로 선택해주세요.", 422
            )
        if start - timedelta(hours=24) <= now or end <= start:
            raise PolicyError(
                "새 모집 마감은 미래이고 종료는 새 시작 이후여야 합니다.", 422
            )
        previous_start = self.starts_at
        previous_version = self.schedule_version
        self.starts_at, self.ends_at = start, end
        self.extension_count += 1
        self.schedule_version += 1
        self.exception_version, self.exception_missing_skills = None, []
        self.refresh_readiness()
        self.emit(
            "SCHEDULE_CHANGED",
            f"schedule:{self.schedule_version}",
            {
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
                "previous_starts_at": previous_start.isoformat(),
                "previous_schedule_version": previous_version,
                "member_ids": [a.member_id for a in self.accepted()],
            },
        )

    def choose_exception(self, member_id, now, expected_version):
        """마지막 모집 종료 후 기술 조건만 면제하는 결정을 기록한다. 즉시 시작하지 않는다."""
        self.require_leader_decision(member_id, now)
        if expected_version != self.schedule_version:
            raise PolicyError("일정 버전이 다릅니다.")
        if self.extension_count != 2 or len(self.accepted()) < 2:
            raise PolicyError(
                "2회 연장 후 확정 인원 최소 2명일 때만 선택할 수 있습니다."
            )
        if not self.missing():
            raise PolicyError(
                "기술 조건을 충족한 프로젝트는 예외 시작 대상이 아닙니다."
            )
        self.exception_version = self.schedule_version
        self.exception_missing_skills = self.missing()
        self.emit(
            "EXCEPTION_SELECTED",
            f"exception:{self.schedule_version}",
            {
                "leader_id": member_id,
                "at": aware(now).isoformat(),
                "missing_skill_ids": self.missing(),
            },
        )

    def cancel(self, member_id, now, reason):
        """팀장의 시작 전 취소를 기록한다. 참여자 자발적 이탈로 집계하지 않는다."""
        self.require_leader_decision(member_id, now)
        if len(self.accepted()) >= 2 and not self.missing():
            raise PolicyError(
                "인원·기술 미달 프로젝트만 팀장 취소를 선택할 수 있습니다."
            )
        self.lifecycle_status, self.termination_reason = "CANCELED", reason
        self.emit(
            "PROGRAM_CANCELED", f"cancel:{self.schedule_version}", {"reason": reason}
        )

    def end_early(self, member_id, now, reason):
        """시작 후 홀로 남은 참여자의 중도 종료를 정상 운영 종료와 구분한다."""
        if self.lifecycle_status != "IN_PROGRESS" or aware(now) >= self.ends_at:
            raise PolicyError("진행 중인 프로젝트에서만 중도 종료할 수 있습니다.")
        members = self.accepted()
        if (
            self.category != "project"
            or len(members) != 1
            or members[0].member_id != member_id
        ):
            raise PolicyError("남은 확정 참여자 1명만 선택할 수 있습니다.", 403)
        self.lifecycle_status, self.termination_reason = "ABORTED", reason
        self.emit(
            "PROGRAM_ABORTED", f"abort:{self.schedule_version}", {"reason": reason}
        )

    def tick(self, now):
        """현재 일정의 전날·시작·종료 작업을 재실행 가능하게 처리한다."""
        now = aware(now)
        if self.lifecycle_status in {"CANCELED", "ABORTED", "COMPLETED"}:
            return
        if now >= self.deadline_at and self.lifecycle_status != "IN_PROGRESS":
            if self.category == "project" and not self.leader_selected:
                self.select_leader(now)
            if self.category == "study" and len(self.accepted()) < 2:
                self.lifecycle_status, self.termination_reason = (
                    "CANCELED",
                    "MINIMUM_NOT_MET",
                )
                self.emit(
                    "PROGRAM_CANCELED",
                    f"cancel:{self.schedule_version}",
                    {
                        "reason": self.termination_reason,
                    },
                )
                return
            if now < self.starts_at:
                self.emit(
                    "DISCORD_PREPARE",
                    f"discord:{self.schedule_version}",
                    {
                        "member_ids": [a.member_id for a in self.accepted()],
                        "starts_at": self.starts_at.isoformat(),
                        "ends_at": self.ends_at.isoformat(),
                        "leader_id": self.leader_id,
                    },
                )
        if now >= self.starts_at and self.lifecycle_status != "IN_PROGRESS":
            permitted = not self.missing() or (
                self.extension_count == 2
                and self.exception_version == self.schedule_version
            )
            if len(self.accepted()) < 2 or not permitted:
                self.lifecycle_status, self.termination_reason = (
                    "CANCELED",
                    "START_CONDITIONS_NOT_MET",
                )
                self.emit(
                    "PROGRAM_CANCELED",
                    f"cancel:{self.schedule_version}",
                    {
                        "reason": self.termination_reason,
                    },
                )
                return
            self.lifecycle_status = "IN_PROGRESS"
        if now >= self.ends_at and self.lifecycle_status == "IN_PROGRESS":
            self.lifecycle_status = "COMPLETED"
            # 운영 종료만으로 개인 완료·XP를 인정하지 않는다.
            self.emit("OPERATING_PERIOD_ENDED", f"ended:{self.schedule_version}", {})

    def permissions(self, member_id, now, restricted=False):
        """표시용 권한. 변경 요청에서도 같은 서버 규칙을 다시 검사해야 한다."""
        item = self.active_application(member_id)
        members = self.accepted()
        missing_skills = self.missing(members=members)
        before_start = aware(now) < self.starts_at
        leader_window = (
            self.category == "project"
            and self.leader_id == member_id
            and self.deadline_at <= aware(now) < self.starts_at
            and self.lifecycle_status in {"RECRUITING", "READY"}
        )
        missing = len(members) < 2 or bool(missing_skills)
        return {
            "can_join": self.is_recruiting(now) and item is None and not restricted,
            "can_cancel_join": item is not None
            and before_start
            and self.lifecycle_status in {"RECRUITING", "READY"},
            "can_edit": self.creator_id == member_id
            and self.lifecycle_status in {"RECRUITING", "READY"},
            "can_extend": leader_window and missing and self.extension_count < 2,
            "can_choose_exception_start": leader_window
            and self.extension_count == 2
            and len(members) >= 2
            and bool(missing_skills),
            "can_cancel_project": leader_window and missing,
            "can_cancel_meetup": leader_window and missing,
            "can_withdraw": self.lifecycle_status == "IN_PROGRESS"
            and item is not None
            and item.status == "ACCEPTED",
            "can_end_early": self.category == "project"
            and self.lifecycle_status == "IN_PROGRESS"
            and len(members) == 1
            and item is not None
            and item.status == "ACCEPTED",
            "can_edit_curriculum": self.category == "study"
            and self.creator_type == "USER"
            and self.creator_id == member_id,
            "can_write_activity": item is not None
            and item.status == "ACCEPTED"
            and self.lifecycle_status == "IN_PROGRESS",
        }
