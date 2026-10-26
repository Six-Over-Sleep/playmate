"""수동 API 검증 전용 앱. 실제 DB/OAuth/XP/봇과 연결하지 않는다.

실행: python -m backend.tests.recruit.manual_api --port 8001
테스트 서버를 종료하면 모든 가상 데이터가 사라진다. 운영 main.py에는 등록하지 않는다.
"""

import argparse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import threading

from fastapi import Depends, FastAPI, Header
from fastapi.openapi.utils import get_openapi
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import ARRAY, BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@compiles(BigInteger, "sqlite")
def sqlite_identity(type_, compiler, **kwargs):
    """격리 SQLite에서 기존 BigInteger PK도 자동 증가하도록 DDL만 변환한다."""
    return "INTEGER"


@compiles(ARRAY, "sqlite")
def sqlite_array(type_, compiler, **kwargs):
    """기존 정기 요일의 테스트 저장 형식. PostgreSQL ARRAY 검증을 대신하지 않는다."""
    return "JSON"


class FixtureCatalog:
    """설명용 기술 사전. 이 숫자들을 실제 공통 기술 사전 ID로 사용하면 안 된다."""

    def names(self, ids):
        names = {101: "Python", 102: "React", 103: "SQL"}
        return {str(skill): names[skill] for skill in ids}

    def validate(self, ids):
        from backend.app.domain.recruit_program import PolicyError

        if not set(ids).issubset({101, 102, 103}):
            raise PolicyError(
                "이 테스트의 기술 ID는 101/Python, 102/React, 103/SQL입니다.", 422
            )


def create_app():
    """실제 설정 대신 안전한 프로세스 환경을 먼저 지정하고 메모리 DB만 생성한다."""
    os.environ.update(
        {
            "APP_ENV": "test",
            "DISCORD_CLIENT_ID": "sandbox",
            "DISCORD_CLIENT_SECRET": "sandbox",
            "DISCORD_REDIRECT_URI": "http://test/callback",
            "SESSION_SECRET_KEY": "manual-sandbox-only",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "1",
            "DB_USER": "sandbox",
            "DB_PASSWORD": "sandbox",
            "DB_NAME": "sandbox",
            "DB_SSLMODE": "disable",
            "DATABASE_URL": "postgresql://sandbox:sandbox@127.0.0.1:1/sandbox",
        }
    )
    from backend.app.core.auth import get_current_member_id
    from backend.app.core.database import Base
    from backend.app.jobs.process_recruit_jobs import process_once
    from backend.app.models.member import Member
    from backend.app.models.comment import Comment
    from backend.app.models.post import Post
    from backend.app.models.post_like import PostLike
    from backend.app.models.post_scrap import PostScrap
    from backend.app.models.recruit import (
        Recruit,
        RecruitMember,
        RecruitStudyDetail,
        RecruitSportsDetail,
        RecruitGameDetail,
        RecruitGroupBuyDetail,
    )
    from backend.app.models.recruit_program import (
        ActivityRecord,
        ApplicationRecord,
        CommandRecord,
        CurriculumRecord,
        EligibilityRecord,
        OutboxRecord,
        ProgramRecord,
        RecognitionRecord,
        WithdrawalRecord,
    )
    from backend.app.repositories.recruit_program_repository import ProgramRepository
    from backend.app.routers.recruit_program import get_service, invoke, features_router
    from backend.app.routers.recruit import router, get_dispatch_service
    from backend.app.services.recruit_dispatch_service import RecruitDispatchService
    from backend.app.schemas.recruit_program import ProgramCreate
    from backend.app.services.recruit_program_service import ProgramService

    sqlite3.register_adapter(list, json.dumps)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    records = [
        Member,
        Post,
        Comment,
        Recruit,
        RecruitMember,
        RecruitStudyDetail,
        RecruitSportsDetail,
        RecruitGameDetail,
        RecruitGroupBuyDetail,
        PostLike,
        PostScrap,
        ProgramRecord,
        ApplicationRecord,
        EligibilityRecord,
        WithdrawalRecord,
        CurriculumRecord,
        ActivityRecord,
        RecognitionRecord,
        OutboxRecord,
        CommandRecord,
    ]
    Base.metadata.create_all(engine, tables=[record.__table__ for record in records])
    clock = [datetime.now(timezone.utc).replace(microsecond=0)]
    initial_start = clock[0] + timedelta(days=4)
    initial_end = clock[0] + timedelta(days=18)
    lock = threading.Lock()
    catalog = FixtureCatalog()

    def make_service(session):
        """공통 XP/인정 정책은 주입하지 않는다. 커리큘럼 기간만 테스트 대역으로 제공한다."""
        return ProgramService(
            ProgramRepository(session),
            catalog,
            lambda: clock[0],
            curriculum_policy=lambda group, now: group.lifecycle_status
            in {"RECRUITING", "READY"},
        )

    def project_payload():
        """현재 테스트 시계 기준 미래의 생성 예시를 제공한다."""
        return {
            "title": "[가상] Python·React 프로젝트",
            "body": "수동 API 테스트용입니다.",
            "category": "project",
            "capacity": 3,
            "recruit_mode": "short",
            "starts_at": (clock[0] + timedelta(days=4)).isoformat(),
            "ends_at": (clock[0] + timedelta(days=18)).isoformat(),
            "required_skill_ids": [101, 102],
            "creator_application": {
                "skill_ids": [101],
                "career_item_ids": [],
                "leader_volunteer": True,
                "direct_input": {},
            },
        }

    with Session(engine) as session:
        session.add_all(
            [
                Member(
                    member_id=index,
                    nickname=f"가상회원{index}",
                    member_status="ACTIVE",
                    role_code="ADMIN" if index == 9 else "USER",
                )
                for index in range(1, 10)
            ]
        )
        session.commit()
        service = make_service(session)
        project = service.create(1, ProgramCreate(**project_payload()))["recruit_id"]
        study = service.create(
            1,
            ProgramCreate(
                title="[가상] 기초 스터디",
                body="선착순/대기 테스트",
                category="study",
                capacity=2,
                starts_at=clock[0] + timedelta(days=4),
                ends_at=clock[0] + timedelta(days=18),
                study_topic="Python",
                study_type="TECHNOLOGY",
                difficulty="BEGINNER",
            ),
        )["recruit_id"]

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(
        title="PlayMate 모임 API · 격리 수동 테스트",
        version="sandbox-only",
        description="실제 로그인/DB가 아닌 가상 회원·메모리 DB입니다. 먼저 /__test__/guide를 실행하세요.",
        lifespan=lifespan,
    )
    app.state.sandbox_engine = engine
    app.add_middleware(
        SessionMiddleware,
        secret_key="manual-sandbox-only",
        session_cookie="sandbox_session",
    )

    def test_member(
        member_id: int = Header(
            default=1,
            ge=1,
            le=9,
            alias="X-Test-Member-ID",
            description="가상 회원 1~8, 관리자 9. 실제 로그인 인증이 아닙니다.",
        )
    ):
        return member_id

    def sandbox_service():
        """SQLite 단일 메모리 연결의 동시 사용을 직렬화한다. 실제 PG 잠금과는 다르다."""
        with lock:
            with Session(engine) as session:
                yield make_service(session)

    app.dependency_overrides[get_current_member_id] = test_member
    app.dependency_overrides[get_service] = sandbox_service

    def sandbox_dispatch(service=Depends(get_service), member_id=Depends(test_member)):
        """main과 같은 분기 서비스를 쓰되 가상 회원/사전만 별도로 주입한다."""
        return RecruitDispatchService(
            service,
            True,
            lambda: member_id,
            lambda: member_id,
            lambda: member_id,
            lambda: member_id,
        )

    app.dependency_overrides[get_dispatch_service] = sandbox_dispatch
    app.include_router(router)
    app.include_router(features_router)

    class Advance(BaseModel):
        hours: float = Field(
            ge=0,
            le=8760,
            description="가상 시계만 앞으로 이동합니다. 실제 PC 시각은 바뀌지 않습니다.",
        )

    @app.get("/__test__/guide", tags=["0. 테스트 안내"])
    def guide(service=Depends(get_service)):
        """가상 회원·샘플 모임 ID·현재 시각·생성/신청 예시를 확인한다."""
        return {
            "mode": "ISOLATED_SQLITE",
            "real_login_tested": False,
            "now": clock[0].isoformat(),
            "project_id": project,
            "study_id": study,
            "members": {"ordinary": [1, 2, 3, 4, 5, 6, 7, 8], "admin": 9},
            "project_create_example": project_payload(),
            "project_join_example": {
                "skill_ids": [102],
                "career_item_ids": [],
                "leader_volunteer": False,
                "direct_input": {"experience": "가상 신청"},
            },
            "study_join_example": {},
            "notice": "실제 DB/OAuth/XP/디스코드에는 연결하지 않습니다. 종료하면 가상 데이터가 사라집니다.",
        }

    @app.post("/__test__/advance", tags=["0. 테스트 안내"])
    def advance(data: Advance, service=Depends(get_service)):
        """가상 시계를 이동하고 전날 마감/시작/종료 작업을 명시적으로 실행한다."""
        clock[0] += timedelta(hours=data.hours)
        return {"now": clock[0].isoformat(), **invoke(process_once, service)}

    def openapi():
        """Swagger 기본 예시를 실제 격리 데이터에 맞춰 바로 실행할 수 있게 만든다."""
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title,
                version=app.version,
                description=app.description,
                routes=app.routes,
            )
            # FastAPI는 override 전 원본 의존성의 헤더를 문서화하므로 수동 테스트 헤더로 맞춘다.
            for path in schema["paths"].values():
                for operation in path.values():
                    for parameter in operation.get("parameters", []):
                        if (
                            parameter.get("in") == "header"
                            and parameter["name"].lower() == "x-dev-member-id"
                        ):
                            parameter.update(
                                name="X-Test-Member-ID",
                                required=False,
                                description="가상 회원 1~8, 관리자 9. 실제 로그인이 아닙니다.",
                                schema={
                                    "type": "integer",
                                    "default": 1,
                                    "minimum": 1,
                                    "maximum": 9,
                                },
                            )
            examples = schema["components"]["schemas"]
            examples["ProgramCreate"]["example"] = project_payload()
            examples["ProgramApplication"]["example"] = {
                "skill_ids": [102],
                "career_item_ids": [],
                "leader_volunteer": False,
                "direct_input": {
                    "skills": [],
                    "education": None,
                    "certificates": None,
                    "experience": "학습 경험을 입력합니다.",
                    "awards": None,
                    "portfolio_url": None,
                },
            }
            examples["Advance"]["example"] = {"hours": 72}
            examples["ExtensionRequest"]["example"] = {
                "starts_at": (initial_start + timedelta(days=2)).isoformat(),
                "ends_at": initial_end.isoformat(),
                "schedule_version": 1,
                "request_key": "manual-extension-1",
            }
            examples["CurriculumUpdate"]["example"] = {
                "version": 1,
                "items": [
                    {"week": 1, "title": "기초 학습", "content": "함께 학습할 내용"}
                ],
            }
            examples["ActivityCreate"]["example"] = {
                "activity_type": "WEEKLY_CHECK",
                "week": 1,
                "submission_stage": None,
                "title": "1주차 인증",
                "body": "학습 내용을 기록합니다.",
                "links": [],
                "attachment_ids": [],
            }
            schema["paths"]["/api/recruits/{recruit_id}/join"]["post"]["requestBody"][
                "content"
            ]["application/json"]["example"] = {
                "skill_ids": [102],
                "career_item_ids": [],
                "leader_volunteer": False,
                "direct_input": {"experience": "React 학습 경험"},
            }
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi
    return app


def main():
    """루프백으로만 바인딩한다. 운영 서버/프론트의 기존 포트를 종료하거나 변경하지 않는다."""
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
