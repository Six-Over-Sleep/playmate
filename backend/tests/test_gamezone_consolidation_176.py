"""GameZone migration SQL static contract checks (Python 3.12+, pytest 8+).

Historical 033/035/063 files remain untouched. This module checks the
final 7-table contract in 065-067 without connecting to any database.
"""

import re
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parents[2] / "database" / "sql"
AUDIT = Path(__file__).resolve().parents[2] / "database" / "audit" / "playmate_db_integrity_check.sql"

FINAL_TABLES = frozenset({
    "games", "game_questions", "game_events", "game_event_entries",
    "game_matches", "game_match_players", "game_attempts",
})

FIRST_REMOVED = frozenset({
    "game_categories", "game_supported_modes", "game_event_questions",
    "game_results", "game_badges", "game_member_badges",
})

FINAL_REMOVED = FIRST_REMOVED | {"game_question_secrets", "game_event_teams"}
INTERMEDIATE_TABLES = FINAL_TABLES | {"game_question_secrets", "game_event_teams"}


def read_sql(filename: str) -> str:
    return (SQL_DIR / filename).read_text(encoding="utf-8-sig")


def dropped_tables(sql: str) -> set[str]:
    return set(re.findall(
        r"(?im)^\s*DROP\s+TABLE\s+public\.([a-z_]+)\s+RESTRICT\s*;",
        sql,
    ))


def test_consolidation_migrations_054_through_067_present():
    for number in range(54, 68):
        assert len(list(SQL_DIR.glob(f"{number:03d}_*.sql"))) == 1


def test_062_drops_exactly_six_legacy_tables():
    sql = read_sql("062_gamezone_consolidation_contract.sql")
    assert dropped_tables(sql) == FIRST_REMOVED
    assert not re.search(r"(?im)^\s*DROP\s+TABLE\b.*\bCASCADE\b", sql)
    assert re.search(r"(?m)^COMMIT;\s*$", sql)


def test_063_verifies_intermediate_nine_table_stage():
    sql = read_sql("063_gamezone_final_verify.sql")
    assert "BEGIN TRANSACTION READ ONLY;" in sql
    for table in INTERMEDIATE_TABLES | FIRST_REMOVED:
        assert f"'{table}'" in sql
    assert "COMMIT;" in sql


def test_065_merges_questions_and_drops_only_secret_table():
    sql = read_sql("065_gamezone_questions_consolidation.sql")
    assert dropped_tables(sql) == {"game_question_secrets"}
    for column in ("answer_key", "judge_config", "answer_updated_at"):
        assert column in sql
    assert "Question answer preservation mismatch" in sql
    assert not re.search(r"(?im)^\s*DROP\s+TABLE\b.*\bCASCADE\b", sql)


def test_066_merges_teams_and_drops_only_team_table():
    sql = read_sql("066_gamezone_teams_consolidation.sql")
    assert dropped_tables(sql) == {"game_event_teams"}
    assert "team_set JSONB" in sql
    assert "Weekly cohort ranking changed during migration" in sql
    for trigger in (
        "trg_validate_game_event_team_set_176",
        "trg_validate_game_player_team_176",
        "trg_protect_game_match_event_team_176",
    ):
        assert trigger in sql
    assert not re.search(r"(?im)^\s*DROP\s+TABLE\b.*\bCASCADE\b", sql)


def test_067_is_read_only_and_covers_exact_final_seven():
    sql = read_sql("067_gamezone_7table_verify.sql")
    assert "BEGIN TRANSACTION READ ONLY;" in sql
    assert sql.rstrip().endswith("COMMIT;")
    for table in FINAL_TABLES | FINAL_REMOVED:
        assert f"'{table}'" in sql
    for fixture in ("Issue 176 migration question", "Issue176 Team A"):
        assert fixture not in sql
    # Ignore comments and read-only SELECTs. Reject executable DML/DDL.
    code = re.sub(r"(?m)^\s*--.*$", "", sql)
    assert not re.search(r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", code, re.I)


def test_final_audit_uses_seven_table_contract_and_unified_badges():
    sql = AUDIT.read_text(encoding="utf-8")
    assert "expected_count=22" in sql
    assert "remaining_legacy_tables" in sql
    assert "fk_member_profile_owned_game_badge" not in sql
    assert "user_notifications_achievement_id_fkey" in sql
    for table in FINAL_TABLES | FINAL_REMOVED:
        assert f"'{table}'" in sql
    assert "answer_key" in sql and "judge_config" in sql


def test_all_removed_table_references_absent_from_updated_views():
    sql = re.sub(r"(?m)^\s*--.*$", "", read_sql("058_gamezone_views_expand.sql"))
    for name in FIRST_REMOVED:
        assert not re.search(rf"\b{re.escape(name)}\b", sql)
