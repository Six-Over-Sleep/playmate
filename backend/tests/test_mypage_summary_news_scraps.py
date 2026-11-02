"""마이페이지 요약 scraps_count = 게시글 스크랩 + 뉴스 스크랩 (Issue #74, #58 협의) — DB 없이 흐름 확인.

실제 SQL·회원 격리·50건 초과·뉴스 테이블 없는 DB는
tests/integration/test_postgres_mypage_summary.py에서 일회용 PostgreSQL로 확인한다.
"""
from contextlib import contextmanager

from fastapi import HTTPException
import psycopg2
import pytest

from app.routers import mypage


SUMMARY = {"posts_count": 2, "comments_count": 5, "received_likes_count": 7,
           "scraps_count": 3, "meetups_count": 1, "total_xp": 120}


class FakeCursor:
    """요약 SQL → 테이블 확인 → 뉴스 COUNT 순서로 결과를 돌려주고 실행한 SQL을 기록한다."""

    def __init__(self, summary, has_table=True, news=1, news_error=None):
        self.results = [summary, {"has_table": has_table}, {"news_scraps": news}]
        self.news_error = news_error
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        if self.news_error and "FROM career_news_scraps" in sql:
            raise self.news_error

    def fetchone(self):
        return self.results[len(self.executed) - 1]


def use(monkeypatch, cursor):
    calls = []

    @contextmanager
    def db_cursor(**kwargs):
        calls.append(kwargs)
        yield cursor

    monkeypatch.setattr(mypage, "db_cursor", db_cursor)
    return calls


def test_adds_news_scraps_and_keeps_other_fields(monkeypatch):
    cursor = FakeCursor(dict(SUMMARY), news=1)
    calls = use(monkeypatch, cursor)
    result = mypage.get_my_activity_summary(member_id=7)
    assert result == {**SUMMARY, "scraps_count": 4}  # 게시글 3 + 뉴스 1, 나머지 필드 그대로
    assert calls == [{"read_only": True}]  # 같은 읽기 전용 연결 하나
    assert "post_scraps" in cursor.executed[0][0] and cursor.executed[0][1] == (7,)  # 기존 요약 SQL 그대로
    assert cursor.executed[1][0] == "SELECT to_regclass('career_news_scraps') IS NOT NULL AS has_table"
    assert cursor.executed[2] == (
        "SELECT COUNT(*)::int AS news_scraps FROM career_news_scraps WHERE member_id = %s", (7,))


def test_news_table_missing_keeps_post_count(monkeypatch):
    cursor = FakeCursor(dict(SUMMARY), has_table=False)
    use(monkeypatch, cursor)
    assert mypage.get_my_activity_summary(member_id=7) == SUMMARY
    assert len(cursor.executed) == 2  # 뉴스 COUNT는 실행하지 않음


def test_missing_member_is_404_without_news_query(monkeypatch):
    cursor = FakeCursor(None)
    use(monkeypatch, cursor)
    with pytest.raises(HTTPException) as error:
        mypage.get_my_activity_summary(member_id=99)
    assert error.value.status_code == 404
    assert len(cursor.executed) == 1


def test_news_count_db_error_is_not_hidden(monkeypatch):
    cursor = FakeCursor(dict(SUMMARY), news_error=psycopg2.errors.InsufficientPrivilege("permission denied"))
    use(monkeypatch, cursor)
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        mypage.get_my_activity_summary(member_id=7)


def test_response_schema_is_unchanged():
    from app.main import app
    from app.schemas.mypage import MyActivitySummaryResponse

    assert {name: field.annotation for name, field in MyActivitySummaryResponse.model_fields.items()} == {
        "posts_count": int, "comments_count": int, "received_likes_count": int,
        "scraps_count": int, "meetups_count": int, "total_xp": int,
    }
    schema = app.openapi()["paths"]["/api/mypage/summary"]["get"]["responses"]["200"]["content"]["application/json"]
    assert schema["schema"]["$ref"].endswith("/MyActivitySummaryResponse")
