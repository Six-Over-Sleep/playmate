"""실제 DB·OAuth를 사용하지 않는 신규 모임 테스트 전용 저장소."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import BigInteger, JSON, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base
from backend.app.models.member import Member
from backend.app.models.post import Post
from backend.app.models.post_like import PostLike
from backend.app.models.post_scrap import PostScrap
from backend.app.models.recruit import Recruit, RecruitMember, RecruitStudyDetail
from backend.app.models import recruit_program
from backend.app.repositories.recruit_program_repository import ProgramRepository
from backend.app.services.recruit_program_service import ProgramService


@compiles(BigInteger, "sqlite")
def sqlite_identity(type_, compiler, **kwargs):
    return "INTEGER"


class Catalog:
    def validate(self, ids):
        from backend.app.domain.recruit_program import PolicyError

        if not set(ids).issubset({101, 102, 103, 104, 105, 106}):
            raise PolicyError("없는 기술입니다.", 422)

    def names(self, ids):
        return {str(skill): f"테스트 기술 {skill}" for skill in ids}


@pytest.fixture
def service(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    # 테스트 엔진만 ARRAY를 JSON으로 저장한다. 운영 PostgreSQL 모델/잠금을 검증했다는 뜻은 아니다.
    column = Recruit.__table__.c.regular_days
    monkeypatch.setattr(column, "type", column.type.with_variant(JSON, "sqlite"))
    tables = [
        Member.__table__,
        Post.__table__,
        Recruit.__table__,
        RecruitMember.__table__,
        RecruitStudyDetail.__table__,
        PostLike.__table__,
        PostScrap.__table__,
    ]
    tables += [
        table
        for table in Base.metadata.sorted_tables
        if table.name.startswith("recruit_")
        and table.name
        not in {
            "recruit_members",
            "recruit_sports_details",
            "recruit_game_details",
            "recruit_study_details",
            "recruit_group_buy_details",
        }
    ]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                Member(
                    member_id=index,
                    member_status="ACTIVE",
                    role_code="ADMIN" if index == 9 else "MEMBER",
                )
                for index in range(1, 10)
            ]
        )
        session.commit()
        now = datetime(2026, 10, 26, 0, tzinfo=timezone.utc)
        clock = [now]
        # 별도 편집 기간 정책을 주입하는 경우도 검증한다. 기본 USER 권한은 개설자 기준이다.
        result = ProgramService(
            ProgramRepository(session),
            Catalog(),
            lambda: clock[0],
            curriculum_policy=lambda program, now: program.lifecycle_status
            in {"RECRUITING", "READY"},
        )
        result.test_clock = clock
        yield result
    engine.dispose()


@pytest.fixture
def payload(service):
    return {
        "title": "기술 스터디",
        "body": "함께 학습합니다.",
        "category": "study",
        "capacity": 2,
        "starts_at": service.clock() + timedelta(days=4),
        "ends_at": service.clock() + timedelta(days=18),
        "study_type": "TECHNOLOGY",
        "difficulty": "BEGINNER",
        "study_topic": "Python",
    }
