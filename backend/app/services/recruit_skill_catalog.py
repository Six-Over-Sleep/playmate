"""DB 기술 사전: 목록 조회와 생성/수정 ID 검증에 동일한 원본을 사용한다."""
from sqlalchemy import inspect, select
from backend.app.domain.recruit_program import PolicyError
from backend.app.models.recruit_program import RecruitSkill


class DatabaseSkillCatalog:
    def __init__(self, session):
        self.session = session

    def options(self):
        bind = self.session.get_bind()
        schema = bind.get_execution_options().get("schema_translate_map", {}).get(None)
        if not inspect(bind).has_table("recruit_skills", schema=schema):
            raise PolicyError("기술 목록을 준비 중이에요. 잠시 후 다시 시도해주세요.", 503)
        return [
            {"skill_id": row.skill_id, "skill_code": row.skill_code, "name": row.name}
            for row in self.session.execute(select(RecruitSkill).order_by(RecruitSkill.name)).scalars()
        ]

    def validate(self, skill_ids):
        known = {item["skill_id"] for item in self.options()}
        if len(skill_ids) != len(set(skill_ids)) or not set(skill_ids).issubset(known):
            raise PolicyError("기술 목록에서 유효한 기술을 중복 없이 선택해주세요.", 422)

    def names(self, skill_ids):
        return {str(item["skill_id"]): item["name"] for item in self.options() if item["skill_id"] in skill_ids}
