
"""Issue #104: 관리자 API 인증·인가 및 권한 회수 회귀 테스트."""

import json
from base64 import b64encode
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from starlette.middleware.sessions import SessionMiddleware

from app.core import auth
from app.routers import admin, board_moderation
from app.services import admin_service


SECRET = "admin-security-104-test"
DISCORD_ID = "isolated-discord-104"

ADMIN_ENDPOINTS = [
    ("GET", "/api/admin/dashboard", None),
    ("GET", "/api/admin/notices", None),
    ("POST", "/api/admin/notices", {"title": "공지", "body": "내용"}),
    ("PATCH", "/api/admin/notices/1", {"title": "수정", "body": "내용"}),
    ("DELETE", "/api/admin/notices/1", None),
    ("GET", "/api/admin/posts", None),
    ("PATCH", "/api/admin/posts/1/visibility", {"hidden": True}),
    ("GET", "/api/admin/members", None),
    ("GET", "/api/admin/meetup-xp/activities", None),
    ("GET", "/api/admin/board-reports", None),
    ("GET", "/api/admin/board-reports/details", None),
]


class FakeCursor:
    def __init__(self, state, kind):
        self.state = state
        self.kind = kind
        self.row = None

    def execute(self, sql, params):
        assert "member_status = 'ACTIVE'" in sql

        if self.kind == "auth":
            valid = (
                self.state["active"]
                and params == (14, DISCORD_ID)
            )
        else:
            assert "role_code" in sql
            valid = (
                self.state["active"]
                and self.state["admin"]
                and params == (14,)
            )

        self.row = {"exists": 1} if valid else None

    def fetchone(self):
        return self.row


def make_cursor(state, kind):
    @contextmanager
    def cursor(**kwargs):
        assert kwargs.get("read_only") is True
        yield FakeCursor(state, kind)

    return cursor


def login_cookie():
    payload = {
        "member_id": 14,
        "user": {"discord_id": DISCORD_ID},
    }
    encoded = b64encode(json.dumps(payload).encode())
    return TimestampSigner(SECRET).sign(encoded).decode()


@pytest.fixture
def security_client(monkeypatch):
    state = {"active": True, "admin": True}

    monkeypatch.setattr(
        auth, "db_cursor", make_cursor(state, "auth")
    )
    monkeypatch.setattr(
        admin_service, "db_cursor", make_cursor(state, "admin")
    )

    # 인증 성공 후 호출되는 대시보드만 대역 처리
    monkeypatch.setattr(
        admin_service, "dashboard", lambda: {"ok": True}
    )

    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key=SECRET,
        session_cookie="playmate_session",
    )
    app.include_router(admin.router)
    app.include_router(board_moderation.admin_router)

    with TestClient(app) as client:
        yield client, state, app


def test_all_admin_endpoints_are_covered(security_client):
    _, _, app = security_client

    # 실제 FastAPI OpenAPI 스키마에서 관리자 API 목록 추출
    schema = app.openapi()

    http_methods = {"get", "post", "put", "patch", "delete"}

    actual = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        if path.startswith("/api/admin")
        for method in operations
        if method.lower() in http_methods
    }

    # 실제 요청 URL을 FastAPI 라우트 정의 형식으로 변환
    expected = {
        (
            method,
            path.replace(
                "/notices/1",
                "/notices/{post_id}",
            ).replace(
                "/posts/1/visibility",
                "/posts/{post_id}/visibility",
            ),
        )
        for method, path, _ in ADMIN_ENDPOINTS
    }

    assert actual == expected, (
        f"\n보안 테스트 누락 API: {actual - expected}"
        f"\n실제 등록되지 않은 API: {expected - actual}"
    )

@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)
def test_admin_endpoints_reject_unauthorized(
    security_client, method, path, body
):
    client, state, _ = security_client

    # 1. 비로그인: 401
    response = client.request(method, path, json=body)
    assert response.status_code == 401, (path, response.text)

    # 2. 정상 로그인한 일반 회원: 403
    client.cookies.set("playmate_session", login_cookie())
    state["admin"] = False

    response = client.request(method, path, json=body)
    assert response.status_code == 403, (path, response.text)


def test_revoked_admin_cannot_reuse_existing_session(security_client):
    client, state, _ = security_client
    client.cookies.set("playmate_session", login_cookie())

    # 최초 관리자 접근
    assert client.get("/api/admin/dashboard").status_code == 200

    # 같은 세션을 유지한 채 DB 관리자 권한 회수
    state["admin"] = False

    assert client.get("/api/admin/dashboard").status_code == 403


def test_inactive_admin_session_is_rejected(security_client):
    client, state, _ = security_client
    client.cookies.set("playmate_session", login_cookie())

    state["active"] = False

    assert client.get("/api/admin/dashboard").status_code == 401


def test_dev_header_cannot_bypass_admin_auth(security_client):
    client, _, _ = security_client

    response = client.get(
        "/api/admin/dashboard",
        headers={"X-Dev-Member-ID": "14"},
    )

    assert response.status_code == 401
