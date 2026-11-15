"""게시글·댓글·신고 시각을 시간대 포함으로 응답하는지 확인한다. DB에 접속하지 않는다.

comments·post_reports의 시각은 시간대 없는 TIMESTAMP(DB 세션 시간대, 공용 DB는 UTC)로
저장된다. 시간대 없이 응답하면 브라우저가 한국 시간으로 해석해 9시간 이르게 표시된다.
"""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.app.services import recruit_comment

APP = Path(__file__).resolve().parents[1] / "app"


def test_recruit_comment_serializes_aware_times():
    comment = SimpleNamespace(
        comment_id=1, parent_comment_id=None, body="본문", author_member_id=3,
        created_at=datetime(2026, 11, 15, 4, 15), updated_at=datetime(2026, 11, 15, 4, 16),
        deleted_at=None,
    )
    result = recruit_comment._serialize_comment(comment, "닉네임", 3, timezone.utc)
    assert result["created_at"].isoformat() == "2026-11-15T04:15:00+00:00"
    assert result["updated_at"].tzinfo is not None


def test_recruit_comment_writes_use_db_clock():
    text = (APP / "services" / "recruit_comment.py").read_text(encoding="utf-8")
    assert "datetime.now()" not in text  # 서버 로컬 시각 사용 금지
    assert "comment.updated_at = func.now()" in text
    assert "comment.deleted_at = func.now()" in text


class _Conn:
    def __init__(self, tz):
        self.tz = tz

    def get_parameter_status(self, name):
        return self.tz if name == "TimeZone" else None


class _Cursor:
    def __init__(self, rows, tz="Etc/UTC"):
        self.rows = rows
        self.connection = _Conn(tz)

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def test_board_comment_rows_get_session_timezone():
    from backend.app.repositories import board_repository

    naive = datetime(2026, 11, 15, 4, 15)
    rows = board_repository.list_comments(_Cursor([{"created_at": naive, "updated_at": naive}]), 1, 1)
    assert rows[0]["created_at"].isoformat() == "2026-11-15T04:15:00+00:00"
    row = board_repository.get_comment(_Cursor([{"created_at": naive, "updated_at": None}], "Asia/Seoul"), 1, 1)
    assert row["created_at"].utcoffset().total_seconds() == 9 * 3600
    assert board_repository.get_comment(_Cursor([]), 1, 1) is None


class _PostCursor(_Cursor):
    """첫 조회는 게시글 행, 이어지는 이미지 일괄 조회는 빈 결과를 돌려준다."""

    def __init__(self, rows, tz="Etc/UTC"):
        super().__init__(rows, tz)
        self.calls = 0

    def execute(self, sql, params=None):
        self.calls += 1

    def fetchall(self):
        return self.rows if self.calls == 1 else []

    def fetchone(self):
        return self.rows[0] if self.rows and self.calls == 1 else None


def test_board_post_rows_get_session_timezone():
    """posts도 시간대 없는 TIMESTAMP라 게시글 작성 시각이 9시간 이르게 보이던 문제."""
    from backend.app.repositories import board_repository

    naive = datetime(2026, 11, 15, 9, 26)
    post = lambda: {"id": 18, "created_at": naive, "updated_at": naive}  # noqa: E731
    rows = board_repository.list_posts(_PostCursor([post()]), 1, "", 1)
    assert rows[0]["created_at"].isoformat() == "2026-11-15T09:26:00+00:00"
    assert rows[0]["updated_at"].tzinfo is not None
    row = board_repository.get_post(_PostCursor([post()]), 1, 18, 1)
    assert row["created_at"].isoformat() == "2026-11-15T09:26:00+00:00"
    assert board_repository.get_post(_PostCursor([]), 1, 18, 1) is None
    featured = board_repository.list_featured_posts(_PostCursor([post()]), "hot", "", 1)
    assert featured[0]["created_at"].tzinfo is not None


def test_comment_and_report_queries_cast_to_timestamptz():
    mypage = (APP / "routers" / "mypage.py").read_text(encoding="utf-8")
    assert "c.created_at::timestamptz AS created_at" in mypage
    moderation = (APP / "routers" / "board_moderation.py").read_text(encoding="utf-8")
    # 요약형·상세형·페이지형(develop #108) 신고 조회 모두 시간대 포함
    assert "MAX(r.created_at) AS" not in moderation
    assert moderation.count("MAX(r.created_at)::timestamptz AS last_reported_at") == 3
    assert moderation.count("r.created_at::timestamptz AS created_at") == 2
