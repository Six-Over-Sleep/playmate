"""신고 로직 단위 테스트. PostgreSQL 연결 없이 서비스 함수를 검증합니다."""

import pytest
from fastapi import HTTPException
from app.routers.board_moderation import ReportCreate, submit_report


class FakeCursor:
    def __init__(self, post=None):
        self.post = post or {
            "post_id": 99,
            "author_member_id": 1,
            "post_status": "PUBLISHED",
            "deleted_at": None,
            "post_type": "BOARD",
            "source_type": "USER",
            "board_name": "자유게시판",
        }
        self.reporters = set()
        self.result = None
        self.sql_log = []
        self.locked = False
        self.hidden_updates = 0

    def execute(self, sql, params=()):
        self.sql_log.append(sql)
        if "FOR UPDATE OF p" in sql:
            self.locked = True
            self.result = dict(self.post)
        elif "INSERT INTO post_reports" in sql:
            assert self.locked, "동시 신고 경쟁을 방지하려면 게시글 잠금이 선행되어야 합니다."
            reporter = params[1]
            self.result = {"report_id": len(self.reporters) + 1} if reporter not in self.reporters else None
            self.reporters.add(reporter)
        elif "COUNT(*)::int AS count FROM post_reports" in sql:
            self.result = {"count": len(self.reporters)}
        elif "UPDATE posts SET post_status = 'HIDDEN'" in sql:
            self.hidden_updates += 1
            self.post["post_status"] = "HIDDEN"
        else:
            raise AssertionError(f"예상하지 못한 SQL: {sql}")

    def fetchone(self):
        return self.result


def report(cursor, member_id, reason="SPAM"):
    cursor.locked = False
    return submit_report(cursor, 7, 99, member_id, ReportCreate(reason=reason))


def test_unique_reporters_three_reports_hide_post():
    cursor = FakeCursor()
    assert report(cursor, 2) == {"post_id": 99, "report_count": 1, "hidden": False}
    assert report(cursor, 3) == {"post_id": 99, "report_count": 2, "hidden": False}
    assert report(cursor, 4) == {"post_id": 99, "report_count": 3, "hidden": True}
    assert cursor.hidden_updates == 1
    assert cursor.post["post_status"] == "HIDDEN"


def test_double_report_returns_409():
    cursor = FakeCursor()
    report(cursor, 2)
    with pytest.raises(HTTPException) as exc:
        report(cursor, 2)
    assert exc.value.status_code == 409
    assert len(cursor.reporters) == 1


def test_cannot_report_own_post():
    with pytest.raises(HTTPException) as exc:
        report(FakeCursor(), 1)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("overrides", [
    {"board_name": "공지사항"},
    {"source_type": "SYSTEM"},
])
def test_system_posts_protected(overrides):
    post = FakeCursor().post | overrides
    with pytest.raises(HTTPException) as exc:
        report(FakeCursor(post), 2)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("overrides", [
    {"post_status": "HIDDEN"},
    {"deleted_at": "2026-11-02"},
    {"post_type": "RECRUIT"},
])
def test_non_published_posts_not_reportable(overrides):
    post = FakeCursor().post | overrides
    with pytest.raises(HTTPException) as exc:
        report(FakeCursor(post), 2)
    assert exc.value.status_code == 404


def test_reason_validation():
    with pytest.raises(ValueError):
        ReportCreate(reason="INVALID")
    with pytest.raises(ValueError):
        ReportCreate(reason="SPAM", details="a" * 501)
