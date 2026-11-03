"""F1·F2 모임 인증 회귀 테스트: 실제 HTTP 라우트와 인증 로직, 격리 SQLite 사용.

외부 Discord 및 공용 PostgreSQL 연결 없이 회원 상태별 접근 제어를 확인한다.
"""
import asyncio
import json
import sys
from base64 import b64encode
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import httpx
import pytest
from itsdangerous import TimestampSigner
from sqlalchemy import text

from app.main import app
from backend.app.core.database import get_db
from backend.app.routers.recruit_program import build_program_service


@pytest.fixture
def api(service, monkeypatch):
    session = service.repository.session
    from backend.app.core.database import Base
    from backend.app.models.comment import Comment
    from backend.app.models.recruit import RecruitGameDetail, RecruitGroupBuyDetail, RecruitSportsDetail

    Base.metadata.create_all(session.get_bind(), tables=[
        RecruitSportsDetail.__table__, RecruitGameDetail.__table__, RecruitGroupBuyDetail.__table__, Comment.__table__,
    ])
    columns = {row[1] for row in session.execute(text("PRAGMA table_info(members)"))}
    if "discord_id" not in columns:  # 테스트 ORM 스키마에 없는 운영 컬럼을 테스트 DB에만 추가
        session.execute(text("ALTER TABLE members ADD COLUMN discord_id TEXT"))
    session.execute(text("UPDATE members SET discord_id = 'd' || member_id"))
    session.execute(text("UPDATE members SET member_status = 'WITHDRAWN' WHERE member_id = 5"))
    session.commit()
    raw = session.get_bind().raw_connection()

    @contextmanager
    def sqlite_cursor(*args, **kwargs):
        cursor = raw.cursor()

        class Adapter:
            def execute(self, sql, params=None):
                cursor.execute(sql.replace("%s", "?"), params or ())

            def fetchone(self):
                return cursor.fetchone()

        try:
            yield Adapter()
        finally:
            cursor.close()

    for name in ("app.core.auth", "backend.app.core.auth"):
        if name in sys.modules:
            monkeypatch.setattr(sys.modules[name], "db_cursor", sqlite_cursor)
    app.dependency_overrides[build_program_service] = lambda: service
    app.dependency_overrides[get_db] = lambda: session

    def call(method, path, member, **kwargs):
        headers = as_member(member) if member is not None else {}

        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await client.request(method, path, headers=headers, **kwargs)

        return asyncio.run(send())

    try:
        yield call
    finally:
        app.dependency_overrides.pop(build_program_service, None)
        app.dependency_overrides.pop(get_db, None)
        raw.close()

def legacy_body(payload):
    return {
        "title": "모임", "body": "본문", "category": "sports", "recruit_mode": "short", "capacity": 6,
        "sport_name": "러닝",
        "deadline_at": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_start": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_end": payload["ends_at"].replace(tzinfo=None).isoformat(),
    }

def cookie(data):
    signed = TimestampSigner("isolated-test-secret").sign(b64encode(json.dumps(data).encode())).decode()
    return {"Cookie": "playmate_session=" + signed}


STATES = {
    "anonymous": {},
    "withdrawn": cookie({"member_id": 5, "user": {"discord_id": "d5"}}),
    "discord_mismatch": cookie({"member_id": 1, "user": {"discord_id": "d2"}}),
    "signup_pending": cookie({"user": {"discord_id": "d-new"}}),
}


def send(method, path, headers=None, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, headers=headers or {}, **kwargs)

    return asyncio.run(run())


def as_member(member_id):
    return cookie({"member_id": member_id, "user": {"discord_id": f"d{member_id}"}})


def program_body(payload):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in payload.items()}


@pytest.fixture
def world(api, payload, service, monkeypatch):
    """작성자 1이 만든 기존 모임 L과 신규 프로그램 P를 준비한다."""
    from backend.app.services import recruit_member

    monkeypatch.setenv("ENABLE_RECRUIT_PROGRAMS", "true")
    monkeypatch.setattr(recruit_member, "kst_now",
                        lambda: service.clock().astimezone(ZoneInfo("Asia/Seoul")).replace(tzinfo=None))
    legacy = send("POST", "/api/recruits", as_member(1), json=legacy_body(payload))
    program = send("POST", "/api/recruits", as_member(1), json=program_body(payload))
    assert legacy.status_code == 201 and program.status_code == 201, (legacy.text, program.text)
    return {"L": legacy.json()["recruit_id"], "P": program.json()["recruit_id"], "payload": payload}


def requests_for(world):
    L, P, payload = world["L"], world["P"], world["payload"]
    reads = [("GET", "/api/recruits", None), ("GET", "/api/recruits/skills", None)]
    writes = [("POST", "/api/recruits", legacy_body(payload)), ("POST", "/api/recruits", program_body(payload))]
    for rid in (L, P):
        reads += [("GET", f"/api/recruits/{rid}", None), ("GET", f"/api/recruits/{rid}/members", None),
                  ("GET", f"/api/recruits/{rid}/count", None), ("GET", f"/api/recruits/{rid}/comments", None)]
        writes += [("PUT", f"/api/recruits/{rid}/like", None), ("DELETE", f"/api/recruits/{rid}/like", None),
                   ("PUT", f"/api/recruits/{rid}/scrap", None), ("DELETE", f"/api/recruits/{rid}/scrap", None),
                   ("POST", f"/api/recruits/{rid}/comments", {"body": "검증 댓글"}),
                   ("POST", f"/api/recruits/{rid}/join", None), ("DELETE", f"/api/recruits/{rid}/join", None),
                   ("PATCH", f"/api/recruits/{rid}", {"title": "변조"}), ("DELETE", f"/api/recruits/{rid}", None)]
    reads += [("GET", f"/api/recruits/{P}/curriculum", None), ("GET", f"/api/recruits/{P}/activities", None)]
    return reads, writes


@pytest.mark.parametrize("state", list(STATES))
def test_every_meetup_api_rejects_non_active_states(world, state):
    reads, writes = requests_for(world)
    before = send("GET", f"/api/recruits/{world['L']}", as_member(2)).json()["title"]
    bad = {}
    for method, path, body in reads + writes:
        response = send(method, path, STATES[state], **({"json": body} if body else {}))
        if response.status_code != 401:
            bad[f"{method} {path}"] = response.status_code
    print(f"[검증] {state}: 요청 {len(reads) + len(writes)}건, 401 아닌 응답 {bad or '없음'}")
    assert not bad
    assert send("GET", f"/api/recruits/{world['L']}", as_member(2)).json()["title"] == before


def test_active_member_flows(world):
    L, P = world["L"], world["P"]
    results = {}
    reads, _ = requests_for(world)
    for method, path, _body in reads:
        results[f"{method} {path}"] = send(method, path, as_member(2)).status_code
    for rid in (L, P):
        for method, path, body in [("PUT", "like", None), ("PUT", "scrap", None), ("POST", "comments", {"body": "정상 댓글"}),
                                   ("POST", "join", None), ("DELETE", "join", None), ("DELETE", "like", None),
                                   ("DELETE", "scrap", None)]:
            results[f"2 {method} /{rid}/{path}"] = send(method, f"/api/recruits/{rid}/{path}", as_member(2),
                                                       **({"json": body} if body else {})).status_code
        results[f"2(타인) PATCH /{rid}"] = send("PATCH", f"/api/recruits/{rid}", as_member(2), json={"title": "타인"}).status_code
        results[f"2(타인) DELETE /{rid}"] = send("DELETE", f"/api/recruits/{rid}", as_member(2)).status_code
        results[f"1(작성자) PATCH /{rid}"] = send("PATCH", f"/api/recruits/{rid}", as_member(1), json={"title": "작성자 수정"}).status_code
    detail = send("GET", f"/api/recruits/{L}", as_member(2)).json()
    members = send("GET", f"/api/recruits/{L}/members", as_member(2)).json()
    results["1(작성자) DELETE /L"] = send("DELETE", f"/api/recruits/{L}", as_member(1)).status_code
    results["삭제 후 GET /L"] = send("GET", f"/api/recruits/{L}", as_member(2)).status_code
    for key, value in results.items():
        print(f"[검증] 활성 회원 {key}: {value}")
    print("[검증] 상세 제목:", detail["title"], "| 참여자 필드:", sorted(members[0].keys()) if members else members)
    assert all(code in (200, 201) for key, code in results.items() if "타인" not in key and "삭제 후" not in key and "DELETE /L" not in key)
    assert all(code == 403 for key, code in results.items() if "타인" in key)
    assert results["1(작성자) DELETE /L"] == 200 and results["삭제 후 GET /L"] == 404


@pytest.mark.parametrize("app_env,header,expected", [
    ("development", "2", 200), ("test", "2", 200), ("DEVELOPMENT", "2", 200),
    ("development", "5", 401), ("development", "999", 401), ("development", "abc", 422), ("development", "-1", 401),
    ("production", "2", 401), ("staging", "2", 401), (None, "2", 401), (" development", "2", 401), ("dev", "2", 401),
])
def test_dev_header_policy(world, monkeypatch, app_env, header, expected):
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    codes = {path: send(method, path, {"X-Dev-Member-ID": header}, **({"json": body} if body else {})).status_code
             for method, path, body in [("GET", "/api/recruits", None),
                                        ("PUT", f"/api/recruits/{world['L']}/like", None),
                                        ("POST", f"/api/recruits/{world['L']}/comments", {"body": "헤더 댓글"})]}
    print(f"[검증] APP_ENV={app_env!r} 헤더={header!r}: {codes}")
    normalized = {200 if code == 201 else code for code in codes.values()}  # 댓글 작성 성공(201)은 성공으로 본다
    assert normalized == {expected}


def test_session_wins_over_dev_header(world, monkeypatch):
    """세션이 있으면 개발 헤더로 다른 회원(2)으로 바꿀 수 없다(댓글 작성자 확인)."""
    monkeypatch.setenv("APP_ENV", "development")
    headers = {**as_member(1), "X-Dev-Member-ID": "2"}
    created = send("POST", f"/api/recruits/{world['L']}/comments", headers, json={"body": "세션 우선"})
    rows = send("GET", f"/api/recruits/{world['L']}/comments", as_member(1)).json()
    mine = [row for row in rows if row["body"] == "세션 우선"]
    print("[검증] 세션+헤더 댓글:", created.status_code, "작성자:", mine[0]["author_id"] if mine else None)
    assert created.status_code == 201 and mine[0]["author_id"] == 1
