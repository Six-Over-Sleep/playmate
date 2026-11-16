"""GameZone migration's static contract; integration DDL checks run in PostgreSQL separately."""

from pathlib import Path
import re


SQL_PATH = Path(__file__).resolve().parents[2] / "database/sql/033_gamezone_schema.sql"
SQL = SQL_PATH.read_text(encoding="utf-8")


EXPECTED_TABLES = {
    "game_categories", "games", "game_supported_modes", "game_questions",
    "game_question_secrets", "game_events", "game_event_questions",
    "game_event_entries", "game_event_teams", "game_matches",
    "game_match_players", "game_attempts", "game_results", "game_badges",
    "game_member_badges",
}


def test_migration_transaction_is_explicit():
    sql = re.sub(r"(?m)^--.*$", "", SQL).strip()
    assert sql.startswith("BEGIN;")
    assert sql.endswith("COMMIT;")
    assert "DROP TABLE" not in sql.upper()
    assert "DELETE FROM PUBLIC." not in sql.upper()


def test_schema_contains_all_gamezone_relations():
    names = set(re.findall(r"CREATE TABLE IF NOT EXISTS public\.([a-z_]+)", SQL))
    assert names == EXPECTED_TABLES
    views = set(re.findall(r"CREATE OR REPLACE VIEW public\.([a-z_]+)", SQL))
    assert views == {
        "v_game_member_rankings",
        "v_game_weekly_cohort_scores",
        "v_game_daily_quiz_scores",
    }


def test_question_secrets_are_separate_from_public_questions():
    public_questions = SQL.split("CREATE TABLE IF NOT EXISTS public.game_questions", 1)[1].split("CREATE TABLE IF NOT EXISTS public.game_question_secrets", 1)[0]
    assert "answer_key" not in public_questions
    assert "judge_config" not in public_questions
    assert "game_question_secrets" in SQL


def test_result_and_event_are_deduplicated():
    assert "PRIMARY KEY (match_id, member_id)" in SQL
    assert "PRIMARY KEY (event_id, member_id)" in SQL
    assert "UNIQUE (member_id, request_id)" in SQL
    assert "uq_game_events_daily_quiz" in SQL
    assert "CHECK (octet_length(submission::text) <= 65536)" in SQL


def test_game_modes_and_topics_seeded():
    for slug in (
        "daily-quiz", "python-quiz", "sql-quiz", "frontend-quiz", "cs-quiz",
        "ai-quiz", "code-challenge", "bug-hunt", "typing-race",
        "reaction-time", "memory-flip", "arcade",
    ):
        assert f"('{slug}'," in SQL
    assert "('typing-race','DUEL')" in SQL
    assert "('typing-race','TEAM')" in SQL
    assert "('PYTHON'," in SQL
    assert "('SQL'," in SQL
    assert "('FRONTEND'," in SQL
    assert "('CS'," in SQL
    assert "('AI'," in SQL
