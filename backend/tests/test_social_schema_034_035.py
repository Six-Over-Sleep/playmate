"""034/035 스키마 계약 정적 검증. 실제 공유 DB 접속 없음."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
SQL_034 = (ROOT / "database/sql/034_member_blocks_direct_messages.sql").read_text(encoding="utf-8")
SQL_035 = (ROOT / "database/sql/035_member_achievements_notifications.sql").read_text(encoding="utf-8")
VERIFY = (ROOT / "database/sql/034_035_social_verify.sql").read_text(encoding="utf-8")


@pytest.mark.parametrize("sql", [SQL_034, SQL_035])
def test_transactional_idempotent(sql):
    assert re.search(r"\bBEGIN;", sql)
    assert sql.rstrip().endswith("COMMIT;")
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert not re.search(r"\b(?:DROP|TRUNCATE|DELETE FROM|ALTER TABLE)\b", sql, flags=re.I)


@pytest.mark.parametrize("table", ["member_blocks", "member_dm_preferences", "dm_conversations", "dm_messages"])
def test_034_has_required_tables(table):
    assert f"CREATE TABLE IF NOT EXISTS public.{table} (" in SQL_034


@pytest.mark.parametrize("table", ["achievement_definitions", "member_achievements", "member_profile_preferences", "notification_preferences", "user_notifications"])
def test_035_has_required_tables(table):
    assert f"CREATE TABLE IF NOT EXISTS public.{table} (" in SQL_035


def test_no_member_reporting_and_preserve_original_tables():
    combined = SQL_034 + SQL_035
    assert "CREATE TABLE IF NOT EXISTS public.member_reports" not in combined
    assert "CREATE TABLE IF NOT EXISTS public.notifications" not in combined
    assert "CREATE TABLE IF NOT EXISTS public.post_reports" not in combined
    assert "CREATE TABLE IF NOT EXISTS public.member_levels" not in combined
    assert "CREATE TABLE IF NOT EXISTS public.member_xp_history" not in combined


def test_block_constraints_and_bidirectional_dm_guard():
    assert "PRIMARY KEY (blocker_member_id, blocked_member_id)" in SQL_034
    assert "blocker_member_id <> blocked_member_id" in SQL_034
    assert "b.blocker_member_id = NEW.sender_member_id" in SQL_034
    assert "b.blocker_member_id = receiver_id" in SQL_034


def test_dm_is_pair_only_with_sender_guard():
    assert "member_low_id < member_high_id" in SQL_034
    assert "uq_dm_conversations_members" in SQL_034
    assert "NEW.sender_member_id NOT IN (low_id, high_id)" in SQL_034
    assert "trg_playmate_dm_message_guard" in SQL_034
    assert "trg_playmate_dm_message_identity_immutable" in SQL_034
    assert "trg_playmate_dm_message_bump_conversation" in SQL_034


def test_dm_idempotency_and_privacy():
    assert "uq_dm_messages_idempotency" in SQL_034
    assert "client_message_id UUID NOT NULL" in SQL_034
    assert "deleted_at IS NOT NULL AND body = ''" in SQL_034
    assert "allow_direct_messages BOOLEAN NOT NULL DEFAULT TRUE" in SQL_034


def test_showcase_badge_cannot_be_unearned():
    assert "REFERENCES public.member_achievements(member_id, achievement_id)" in SQL_035
    assert "REFERENCES public.game_member_badges(member_id, badge_id)" in SQL_035
    assert "NUM_NONNULLS(featured_achievement_id, featured_game_badge_id) <= 1" in SQL_035
    assert "CREATE OR REPLACE VIEW public.v_member_all_achievements" in SQL_035


def test_notifications_are_internal_and_deduplicated():
    assert "CREATE TABLE IF NOT EXISTS public.user_notifications" in SQL_035
    assert "uq_user_notifications_event" in SQL_035
    assert "idx_user_notifications_unread" in SQL_035
    assert "notification_type <> 'SYSTEM' OR enabled" in SQL_035
    assert "DM_MESSAGE" in SQL_035


def test_verify_script_is_read_only():
    assert "actual_tables" in VERIFY and "actual_views" in VERIFY
    assert "post_reports_preserved" in VERIFY and "discord_queue_preserved" in VERIFY
    assert not re.search(r"\b(?:INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b", VERIFY, flags=re.I)
