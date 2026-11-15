"""psycopg3·SQLAlchemy 연결도 운영에서 DB_SSLMODE=disable을 거부하는지 확인한다. DB에 접속하지 않는다.

운영 조건 재현에서 DB_SSLMODE=disable로 기동하자 psycopg2 경로(db_connect)와 달리
core/database.py는 암호화 없이 접속을 시도했다(서버 pg_hba가 거부해서야 실패).
"""

import pytest

from backend.app.core import database


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(database.psycopg, "connect", fake_connect)
    return calls


def test_direct_connection_refuses_plaintext_in_production(monkeypatch, captured):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DB_SSLMODE", "disable")
    with pytest.raises(RuntimeError, match="DB_SSLMODE=require"):
        database.get_db_connection()
    assert captured == []


def test_direct_connection_uses_require_in_production(monkeypatch, captured):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DB_SSLMODE", "require")
    database.get_db_connection()
    assert captured[0]["sslmode"] == "require"


def test_local_development_may_disable_ssl(monkeypatch, captured):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DB_SSLMODE", "disable")
    database.get_db_connection()
    assert captured[0]["sslmode"] == "disable"


def test_orm_engine_refuses_plaintext_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DB_SSLMODE", "disable")
    cparams = {}
    with pytest.raises(RuntimeError, match="DB_SSLMODE=require"):
        database._enforce_sslmode(None, None, (), cparams)
    monkeypatch.setenv("DB_SSLMODE", "require")
    database._enforce_sslmode(None, None, (), cparams)
    assert cparams["sslmode"] == "require"
