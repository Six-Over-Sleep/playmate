"""베타 보안 설정(#82): 환경별 세션 쿠키·API 문서·개발용 헤더·내부 정보 노출을 검증한다.

main.py는 import 시점의 APP_ENV로 앱을 구성하므로, 환경별 앱은 main.py를 별도 모듈로
다시 실행해 만든다. 공용 app.main 객체와 다른 테스트에는 영향을 주지 않는다.
DB는 모두 대역을 사용하며 실제 DB에 접속하지 않는다.
"""

import importlib.util
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app import main as main_module
from app.core import auth

MAIN_PATH = Path(main_module.__file__)
FIXED_DETAIL = "일시적인 서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


def load_main(monkeypatch, app_env):
    """APP_ENV(None이면 미설정)를 적용한 main.py의 새 앱을 만든다."""
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    spec = importlib.util.spec_from_file_location(f"main_for_{app_env}", MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forbid_auth_db(monkeypatch):
    """운영 개발헤더 거부가 DB 조회 없이 일어나는지 확인하도록 인증 모듈의 DB 접근을 막는다."""
    used = MagicMock(side_effect=AssertionError("인증 DB 조회가 일어나면 안 됩니다."))
    for name in ("app.core.auth", "backend.app.core.auth"):
        if name in sys.modules:
            monkeypatch.setattr(sys.modules[name], "db_cursor", used)
    return used


def cookie_attributes(response):
    header = response.headers["set-cookie"]
    name_value, *attributes = [part.strip().lower() for part in header.split(";")]
    return name_value, set(attributes)


# ---------------------------------------------------------
# 1~3. 세션 쿠키 Secure·HttpOnly·SameSite
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "app_env,secure",
    [
        ("production", True),
        (None, True),  # 미설정은 운영으로 본다
        ("staging", True),  # 알 수 없는 값도 운영으로 본다
        ("development", False),
        ("test", False),
    ],
)
def test_session_cookie_flags_by_environment(monkeypatch, app_env, secure):
    main = load_main(monkeypatch, app_env)
    client = TestClient(main.app, base_url="https://testserver")

    response = client.get("/auth/discord/login", follow_redirects=False)

    assert response.status_code == 302
    name_value, attributes = cookie_attributes(response)
    assert name_value.startswith("playmate_session=")
    assert ("secure" in attributes) is secure
    assert "httponly" in attributes
    assert "samesite=lax" in attributes


def _add_session_probe(app):
    @app.get("/__session_probe")
    def probe(request: Request):
        return {"has_state": "oauth_state" in request.session}


def test_development_session_works_over_local_http(monkeypatch):
    """로컬 HTTP 개발 환경에서는 로그인 시작 시 만든 세션이 다음 요청에 그대로 전달된다."""
    main = load_main(monkeypatch, "development")
    _add_session_probe(main.app)
    client = TestClient(main.app, base_url="http://localhost")

    client.get("/auth/discord/login", follow_redirects=False)

    assert client.get("/__session_probe").json() == {"has_state": True}


def test_production_session_cookie_is_sent_only_over_https(monkeypatch):
    main = load_main(monkeypatch, "production")
    _add_session_probe(main.app)

    plain = TestClient(main.app, base_url="http://testserver")
    plain.get("/auth/discord/login", follow_redirects=False)
    assert plain.get("/__session_probe").json() == {"has_state": False}

    secure = TestClient(main.app, base_url="https://testserver")
    secure.get("/auth/discord/login", follow_redirects=False)
    assert secure.get("/__session_probe").json() == {"has_state": True}


# ---------------------------------------------------------
# 4~5. 개발용 X-Dev-Member-ID 헤더
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["/api/boards", "/api/mypage/summary", "/api/admin/dashboard", "/api/activity/ping"],
)
@pytest.mark.parametrize("app_env", ["production", None, "staging"])
def test_production_rejects_dev_header_without_db_lookup(monkeypatch, app_env, path):
    main = load_main(monkeypatch, app_env)
    used = forbid_auth_db(monkeypatch)
    client = TestClient(main.app, base_url="https://testserver")

    method = client.post if path.endswith("/ping") else client.get
    response = method(path, headers={"X-Dev-Member-ID": "1"})

    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 필요합니다."}
    used.assert_not_called()


def test_production_recruit_dispatch_rejects_dev_header(monkeypatch):
    """모임 API의 회원 확인도 운영에서는 개발 헤더를 받지 않는다.

    활성 회원 전용 정책으로 의존성 생성 시점에 바로 인증하므로 그 단계에서 401이 난다.
    """
    from backend.app.routers.recruit import get_dispatch_service

    monkeypatch.setenv("APP_ENV", "production")
    used = forbid_auth_db(monkeypatch)
    request = Request({"type": "http", "headers": [], "session": {}})

    with pytest.raises(HTTPException) as error:
        get_dispatch_service(request, MagicMock(), x_dev_member_id=1)

    assert error.value.status_code == 401
    used.assert_not_called()


def _whoami_app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="isolated-test-secret")

    @app.get("/whoami")
    def whoami(member_id: int = Depends(auth.get_current_member_id)):
        return {"member_id": member_id}

    return app


@contextmanager
def _member_exists_cursor(*_, **__):
    cursor = MagicMock()
    cursor.fetchone.return_value = {"exists": 1}
    yield cursor


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_development_dev_header_still_authenticates(monkeypatch, app_env):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setattr(auth, "db_cursor", _member_exists_cursor)
    client = TestClient(_whoami_app())

    response = client.get("/whoami", headers={"X-Dev-Member-ID": "7"})

    assert response.status_code == 200
    assert response.json() == {"member_id": 7}


# ---------------------------------------------------------
# 6~7. API 문서
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "app_env,status",
    [("production", 404), (None, 404), ("staging", 404), ("development", 200), ("test", 200)],
)
def test_api_docs_by_environment(monkeypatch, app_env, status):
    main = load_main(monkeypatch, app_env)
    client = TestClient(main.app)

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == status, path


def test_development_openapi_still_lists_routes(monkeypatch):
    main = load_main(monkeypatch, "development")
    paths = TestClient(main.app).get("/openapi.json").json()["paths"]
    assert "/api/boards" in paths and "/health/db" in paths


# ---------------------------------------------------------
# 8. /health/db
# ---------------------------------------------------------

def test_health_db_hides_database_name(monkeypatch):
    executed = []

    @contextmanager
    def fake_cursor(*_, **__):
        cursor = MagicMock()
        cursor.execute.side_effect = lambda sql, *args: executed.append(sql)
        cursor.fetchone.return_value = {"connected": 1, "database_name": "internal_db_name"}
        yield cursor

    monkeypatch.setattr(main_module, "db_cursor", fake_cursor)

    response = TestClient(main_module.app).get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "internal_db_name" not in response.text
    assert all("current_database" not in sql for sql in executed)


# ---------------------------------------------------------
# 9. RuntimeError 응답
# ---------------------------------------------------------

def test_health_db_connection_failure_returns_fixed_message(monkeypatch):
    def broken(*_, **__):
        raise RuntimeError("누락된 DB 환경변수: DB_PASSWORD")

    monkeypatch.setattr(main_module, "db_cursor", broken)

    response = TestClient(main_module.app).get("/health/db")

    assert response.status_code == 503
    assert response.json() == {"detail": FIXED_DETAIL}
    assert "DB_PASSWORD" not in response.text


@pytest.mark.parametrize("app_env", ["production", "development"])
def test_runtime_error_response_hides_internal_message(monkeypatch, caplog, app_env):
    main = load_main(monkeypatch, app_env)

    @main.app.get("/__boom")
    def boom():
        raise RuntimeError("connect failed host=private-db-host password=private-pass")

    with caplog.at_level(logging.ERROR):
        response = TestClient(main.app).get("/__boom?code=private-oauth-code")

    assert response.status_code == 503
    assert response.json() == {"detail": FIXED_DETAIL}
    for secret in ("private-db-host", "private-pass", "private-oauth-code"):
        assert secret not in response.text
    # 서버 로그에는 원인 추적용 경로·예외 종류가 남고, 쿼리 문자열은 남지 않는다.
    assert "GET /__boom (RuntimeError)" in caplog.text
    assert "private-oauth-code" not in caplog.text
