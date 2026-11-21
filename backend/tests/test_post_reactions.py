"""좋아요·스크랩·신고를 post_reactions 한 테이블로 합친 구조(045, #159)를 고정한다. DB에 접속하지 않는다."""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from backend.app.models.post_like import PostLike
from backend.app.models.post_reaction import PostReaction
from backend.app.models.post_scrap import PostScrap
from backend.app.repositories import recruit as recruit_repo

ROOT = Path(__file__).resolve().parents[2]


def _sql(statement) -> str:
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


def test_like_and_scrap_models_share_post_reactions():
    assert PostLike.__table__ is PostScrap.__table__ is PostReaction.__table__
    assert PostReaction.__tablename__ == "post_reactions"
    assert [c.name for c in PostReaction.__table__.primary_key] == ["post_id", "reaction_type", "member_id"]


def test_orm_queries_filter_by_reaction_type_automatically():
    """모임 코드의 select(PostLike...)·outerjoin(PostLike...)는 고치지 않아도 종류 조건이 붙는다."""
    like_sql = _sql(select(func.count(PostLike.member_id)).where(PostLike.post_id == 1))
    scrap_sql = _sql(select(PostScrap.member_id).where(PostScrap.post_id == 1))
    assert "FROM post_reactions" in like_sql and "post_reactions.reaction_type IN" in like_sql
    assert "FROM post_reactions" in scrap_sql and "post_reactions.reaction_type IN" in scrap_sql


class _Session:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)


def test_recruit_like_and_scrap_insert_set_type_and_conflict_target():
    """INSERT에는 종류 값이 자동으로 붙지 않으므로 저장 코드가 직접 넣는다."""
    session = _Session()
    recruit_repo.add_post_like(session, 5, 7)
    recruit_repo.add_post_scrap(session, 5, 7)
    like_sql, scrap_sql = (_sql(s) for s in session.statements)
    for sql in (like_sql, scrap_sql):
        assert sql.startswith("INSERT INTO post_reactions (") and "reaction_type" in sql.split("VALUES")[0]
        assert "ON CONFLICT (post_id, reaction_type, member_id) DO NOTHING" in sql
    like_params = session.statements[0].compile(dialect=postgresql.dialect()).params
    scrap_params = session.statements[1].compile(dialect=postgresql.dialect()).params
    assert like_params["reaction_type"] == "LIKE" and scrap_params["reaction_type"] == "SCRAP"


def test_member_withdrawal_keeps_report_rows():
    """탈퇴 정리는 예전처럼 좋아요·스크랩만 지우고 신고 기록은 남긴다."""
    text = (ROOT / "backend/app/services/member_service.py").read_text(encoding="utf-8")
    assert "DELETE FROM public.post_reactions WHERE member_id = %s AND reaction_type IN ('LIKE', 'SCRAP')" in text


def test_migration_preserves_report_ids_and_checks_counts():
    sql = (ROOT / "database/sql/045_post_reactions.sql").read_text(encoding="utf-8")
    assert "SELECT report_id, post_id, reporter_member_id, 'REPORT', reason, details, created_at" in sql
    assert "PRIMARY KEY (post_id, reaction_type, member_id)" in sql
    for name in ("신고", "좋아요", "스크랩"):
        assert f"{name} 이관 건수 불일치" in sql
