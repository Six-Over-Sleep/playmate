"""타인 신청 이전의 모임 종류 전환. 기존 모임 ID와 게시글 연결은 유지한다."""

from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from backend.app.domain.recruit_program import PolicyError
from backend.app.schemas.recruit_dispatch import RecruitCreation
from backend.app.schemas.recruit_program import ProgramCreate
from backend.app.services import recruit as legacy


class RecruitConfigurationService:
    def __init__(self, programs):
        self.programs = programs
        self.repository = programs.repository

    def allowed(self, recruit_id, member_id, *, lock=False):
        """취소한 신청도 이력에 포함하고, 서버 시각으로 기존 모집 마감을 검사한다."""
        context = self.repository.configuration_context(recruit_id, lock)
        return self.allowed_context(context, member_id)

    def allowed_context(self, context, member_id):
        """이미 읽은 행과 이력 집계를 재사용해 동일 조건을 판단한다."""
        recruit, post, history = context
        now = self.programs.clock()
        deadline = recruit.deadline_at
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        allowed = (
            member_id is not None and post.author_member_id == member_id
            and not history and recruit.state == "OPEN"
            and deadline is not None and now < deadline
        )
        return allowed

    def change(self, recruit_id, member_id, changes):
        """대상 종류의 생성 계약으로 전체 입력을 검증한 뒤 원자적으로 전환한다."""
        # 회원 → 프로그램 → 기존 모임 순으로 참여 경로와 동일하게 잠근다.
        self.repository.actor(member_id, lock=True)
        if self.repository.is_program(recruit_id):
            old_program = self.repository.load(recruit_id, lock=True)
            if old_program.creator_id != member_id:
                raise PolicyError("모임 개설자만 변경할 수 있습니다.", 403)
            if not old_program.permissions(member_id, self.programs.clock())[
                "can_edit_configuration"
            ]:
                raise PolicyError("다른 사람의 신청 이력이 없고 모집 마감 전일 때만 변경할 수 있습니다.")
        context = self.repository.configuration_context(recruit_id, lock=True)
        if context[1].author_member_id != member_id:
            raise PolicyError("모임 개설자만 변경할 수 있습니다.", 403)
        if not self.allowed_context(context, member_id):
            raise PolicyError("다른 사람의 신청 이력이 없고 모집 마감 전일 때만 변경할 수 있습니다.")
        values = {
            "contact_method": context[0].contact_method,
            **changes,
        }
        data = TypeAdapter(RecruitCreation).validate_python(values)
        if isinstance(data, ProgramCreate):
            # 생성과 동일한 기술·개설자·관리자 검증을 재사용한다.
            return self.programs.create(member_id, data, existing_recruit_id=recruit_id)
        if data.category not in {"sports", "game", "group_buy", "study"}:
            raise PolicyError("지원하지 않는 모임 종류입니다.", 422)
        if data.category == "group_buy" and data.recruit_mode != "short":
            raise PolicyError("공동구매는 단기 형태만 사용할 수 있습니다.", 422)
        required = {
            "sports": ("sport_name",),
            "game": ("game_name",),
            "group_buy": ("product_name", "pickup_method"),
        }
        if any(not getattr(data, key) for key in required.get(data.category, ())):
            raise PolicyError("변경할 종류의 필수 정보를 입력해주세요.", 422)
        now = self.programs.clock()
        deadline = data.deadline_at.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        if now >= deadline:
            raise PolicyError("새 모집 마감은 미래여야 합니다.", 422)
        detail_model, detail_values = legacy._get_detail_model_and_values(data)
        with self.programs.transaction():
            self.repository.reset_configuration(recruit_id)
            self.repository.configure_legacy(
                recruit_id, data, detail_model, detail_values, now
            )
        return {"recruit_id": recruit_id, "message": "모임 종류를 변경했습니다."}
