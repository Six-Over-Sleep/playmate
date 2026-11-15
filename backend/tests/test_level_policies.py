"""level_policies 기반 레벨 계산 단위 테스트. DB에 접속하지 않는다."""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from psycopg2.errors import UndefinedTable

from backend.app.services.xp_service import (
    calculate_level,
    level_for_xp,
    level_progress,
    read_level_thresholds,
    validate_level_thresholds,
)

# 025_level_policies.sql 초기값
OVERALL = [(1, 0), (2, 100), (3, 500), (4, 1500)]
SKILL = [(1, 0), (2, 50), (3, 150), (4, 300), (5, 500)]


@pytest.mark.parametrize(
    "xp,level", [(0, 1), (99, 1), (100, 2), (499, 2), (500, 3), (1499, 3), (1500, 4), (99999, 4)]
)
def test_overall_level_boundaries(xp, level):
    assert level_for_xp(OVERALL, xp) == level


@pytest.mark.parametrize("xp,level", [(49, 1), (50, 2), (150, 3), (300, 4), (499, 4), (500, 5)])
def test_skill_level_boundaries(xp, level):
    assert level_for_xp(SKILL, xp) == level


def test_progress_matches_previous_api_values():
    assert level_progress(OVERALL, 41) == {
        "level": 1, "next_level_xp": 100, "remaining_xp": 59, "progress_percent": 41.0,
    }
    assert level_progress(OVERALL, 300) == {
        "level": 2, "next_level_xp": 500, "remaining_xp": 200, "progress_percent": 50.0,
    }
    assert level_progress(OVERALL, 2000) == {
        "level": 4, "next_level_xp": None, "remaining_xp": 0, "progress_percent": 100.0,
    }
    assert level_progress(SKILL, 100)["next_level_xp"] == 150


def test_changed_policy_is_used():
    assert level_for_xp([(1, 0), (2, 10)], 10) == 2


def test_negative_xp_rejected():
    with pytest.raises(ValueError):
        level_for_xp(OVERALL, -1)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [(1, 5), (2, 100)],          # 1레벨이 0XP가 아님
        [(1, 0), (3, 500)],          # 레벨 누락
        [(1, 0), (2, 100), (3, 100)],  # 증가하지 않음
        [(1, 0), (2, 500), (3, 100)],  # 역순 기준
    ],
)
def test_invalid_policy_returns_503(rows):
    with pytest.raises(HTTPException) as exc:
        validate_level_thresholds(rows)
    assert exc.value.status_code == 503


def test_read_thresholds_accepts_dict_and_tuple_rows():
    cursor = Mock()
    cursor.fetchall.return_value = [{"level": 2, "min_xp": 100}, {"level": 1, "min_xp": 0}]
    assert read_level_thresholds(cursor) == [(1, 0), (2, 100)]
    cursor.fetchall.return_value = [(1, 0), (2, 100)]
    assert calculate_level(cursor, 150) == 2
    assert cursor.execute.call_args.args[1] == ("OVERALL",)


def test_missing_table_returns_503():
    cursor = Mock()
    cursor.execute.side_effect = UndefinedTable("relation \"level_policies\" does not exist")
    with pytest.raises(HTTPException) as exc:
        read_level_thresholds(cursor, "SKILL")
    assert exc.value.status_code == 503
