"""Issue #176: GameZone final schema migration contracts."""

import re
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parents[2] / "database" / "sql"

FINAL_TABLES = {
    "games",
    "game_questions",
    "game_question_secrets",
    "game_events",
    "game_event_entries",
    "game_event_teams",
    "game_matches",
    "game_match_players",
    "game_attempts",
}

REMOVED_TABLES = {
    "game_categories",
    "game_supported_modes",
    "game_event_questions",
    "game_results",
    "game_badges",
    "game_member_badges",
}


def read_sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8-sig")


def test_all_consolidation_migrations_exist():
    numbers = range(54, 65)
    for number in numbers:
        files = list(SQL_DIR.glob(f"{number:03d}_*.sql"))
        assert len(files) == 1, f"Expected one migration for {number:03d}"


def test_contract_removes_exactly_six_tables():
    sql = read_sql("062_gamezone_consolidation_contract.sql")

    dropped = set(re.findall(
        r"(?im)^\s*DROP TABLE public\.([a-z_]+)\s+RESTRICT\s*;",
        sql,
    ))

    assert dropped == REMOVED_TABLES
    assert not re.search(r"(?im)^\s*DROP TABLE .*CASCADE", sql)
    assert "COMMIT;" in sql


def test_final_verification_covers_nine_tables():
    sql = read_sql("063_gamezone_final_verify.sql")

    assert "BEGIN TRANSACTION READ ONLY;" in sql

    for name in FINAL_TABLES | REMOVED_TABLES:
        assert f"'{name}'" in sql

    assert "COMMIT;" in sql


def test_rankings_no_longer_reference_legacy_tables():
    sql = read_sql("058_gamezone_views_expand.sql")

    # SQL 주석을 제외하고 실제 View 정의만 검사
    sql = re.sub(r"(?m)^\s*--.*$", "", sql)

    for name in REMOVED_TABLES:
        assert not re.search(rf"\b{re.escape(name)}\b", sql)


def test_private_question_secrets_are_preserved():
    sql = read_sql("062_gamezone_consolidation_contract.sql")

    assert "DROP TABLE public.game_question_secrets" not in sql
    assert "DROP TABLE public.game_questions" not in sql
