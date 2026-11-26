"""DB 기술 사전: 목록 조회와 생성/수정 ID 검증에 동일한 원본을 사용한다."""

from sqlalchemy import inspect, select

from backend.app.domain.recruit_program import PolicyError
from backend.app.models.recruit_program import RecruitSkill


class DatabaseSkillCatalog:
    """요청 세션의 연결과 트랜잭션을 공유하는 기술 사전 접근 객체."""

    def __init__(self, session):
        self.session = session

    def options(self):
        """추가 연결 없이 테이블 준비 상태를 검사하고 기술 목록을 읽는다."""
        # 엔진을 inspect하면 별도 연결을 빌린다. 연결 한도가 1개여도
        # 회원 조회가 확보한 연결을 그대로 쓰도록 세션의 연결을 검사한다.
        connection = self.session.connection()
        schema_map = connection.get_execution_options().get("schema_translate_map")
        schema = (schema_map or {}).get(None)
        if not inspect(connection).has_table("recruit_skills", schema=schema):
            raise PolicyError("기술 목록을 준비 중이에요. 잠시 후 다시 시도해주세요.", 503)
        statement = select(RecruitSkill).order_by(RecruitSkill.name)
        return [
            {"skill_id": row.skill_id, "skill_code": row.skill_code, "name": row.name}
            for row in self.session.execute(statement).scalars()
        ]

    def validate(self, skill_ids):
        """사전에 없는 기술과 중복 선택을 거부한다."""
        known = {item["skill_id"] for item in self.options()}
        if len(skill_ids) != len(set(skill_ids)) or not set(skill_ids).issubset(known):
            raise PolicyError("기술 목록에서 유효한 기술을 중복 없이 선택해주세요.", 422)

    def names(self, skill_ids):
        """모임에 저장할 선택 기술의 이름을 같은 사전에서 조회한다."""
        selected = set(skill_ids)
        return {
            str(item["skill_id"]): item["name"]
            for item in self.options()
            if item["skill_id"] in selected
        }
