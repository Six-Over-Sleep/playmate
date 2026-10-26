"""기존 계약을 보존하면서 신규 프로그램으로 명시적으로 분기하는 모임 진입 서비스."""

from backend.app.domain.recruit_program import PolicyError
from backend.app.schemas.recruit import RecruitUpdate
from backend.app.schemas.recruit_program import (
    ProgramApplication,
    ProgramCreate,
    ProgramEdit,
)
from backend.app.services import recruit as legacy
from backend.app.services import recruit_member as legacy_members


class RecruitDispatchService:
    def __init__(
        self,
        program_service,
        enabled,
        current_member,
        optional_member,
        legacy_member,
        legacy_optional_member,
    ):
        self.programs = program_service
        self.repository = program_service.repository
        self.db = self.repository.session
        self.enabled = enabled
        self.current_member = current_member
        self.optional_member = optional_member
        self.legacy_member = legacy_member
        self.legacy_optional_member = legacy_optional_member

    def require_enabled(self):
        """운영 설정과 실제 마이그레이션 준비를 검사한다. 가짜 성공이나 자동 DDL은 하지 않는다."""
        if not self.enabled:
            raise PolicyError(
                "신규 모임 API를 활성화하지 않았습니다. 배포 설정을 확인해주세요.", 503
            )
        if not self.repository.schema_available():
            raise PolicyError("신규 모임 마이그레이션을 먼저 적용해주세요.", 503)

    def is_program(self, recruit_id):
        """기존 스터디와 신규 스터디를 category 문자열이 아니라 저장된 확장 행으로 구분한다."""
        return self.repository.is_program(recruit_id)

    def create(self, data):
        if isinstance(data, ProgramCreate):
            self.require_enabled()
            return self.programs.create(self.current_member(), data)
        return legacy.create_recruit(self.db, data, self.legacy_member())

    def detail(self, recruit_id):
        if self.is_program(recruit_id):
            self.require_enabled()
            return self.programs.detail(recruit_id, self.optional_member())
        return legacy.get_recruit(self.db, recruit_id, self.legacy_optional_member())

    def list(self, category=None):
        """기존 목록 순서와 배열을 유지하고 신규 행만 확장 응답으로 바꾼다."""
        if category not in {None, "project", "study", "sports", "game", "group_buy"}:
            raise PolicyError("지원하지 않는 모임 종류입니다.", 422)
        records = legacy.get_recruits(self.db, category)
        if not self.enabled:
            program_ids = self.repository.program_ids()
            return [item for item in records if item["recruit_id"] not in program_ids]
        self.require_enabled()
        if category not in {None, "project", "study"} or not records:
            return records
        programs = {
            item["recruit_id"]: item
            for item in self.programs.list(
                self.optional_member(), category, base_rows=records
            )
        }
        return [programs.get(item["recruit_id"], item) for item in records]

    def update(self, recruit_id, changes):
        if self.is_program(recruit_id):
            self.require_enabled()
            return self.programs.edit(
                recruit_id, self.current_member(), ProgramEdit.model_validate(changes)
            )
        # 신규 필드는 legacy extra 무시로 사라지지 않도록 명시적으로 거절한다.
        unknown = set(changes) - set(RecruitUpdate.model_fields)
        if unknown:
            raise PolicyError("기존 모임이 지원하지 않는 수정 필드입니다.", 422)
        return legacy.update_recruit(
            self.db, recruit_id, RecruitUpdate.model_validate(changes)
        )

    def delete(self, recruit_id):
        if self.is_program(recruit_id):
            self.require_enabled()
            return self.programs.archive(recruit_id, self.current_member())
        return legacy.delete_recruit(self.db, recruit_id)

    def apply(self, recruit_id, data):
        if self.is_program(recruit_id):
            self.require_enabled()
            return self.programs.apply(
                recruit_id,
                self.current_member(),
                ProgramApplication.model_validate(data or {}),
            )
        if data:
            raise PolicyError("기존 모임은 프로젝트 신청서를 받지 않습니다.", 422)
        return legacy_members.join_recruit(self.db, recruit_id)

    def cancel_application(self, recruit_id):
        if self.is_program(recruit_id):
            self.require_enabled()
            return self.programs.cancel_application(recruit_id, self.current_member())
        return legacy_members.cancel_join(self.db, recruit_id)

    def members(self, recruit_id):
        if self.is_program(recruit_id):
            self.require_enabled()
            return self.programs.members(recruit_id, self.optional_member())
        return legacy_members.get_recruit_members(self.db, recruit_id)

    def count(self, recruit_id):
        if self.is_program(recruit_id):
            self.require_enabled()
            return self.programs.count(recruit_id, self.optional_member())
        return legacy_members.get_recruit_count(self.db, recruit_id)
