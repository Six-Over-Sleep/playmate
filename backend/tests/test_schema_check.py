"""배포 전 필수 스키마·XP 정책 검사(core/schema_check.py). DB에 접속하지 않는다."""

import pytest

from backend.app.core import schema_check
from backend.app.core.schema_check import REQUIRED_LIMITS, check_schema, required_award_types

OVERALL = [(1, 0), (2, 100), (3, 500), (4, 1500)]
SKILL = [(1, 0), (2, 50), (3, 150), (4, 300), (5, 500)]


class FakeCursor:
    """information_schema·정책 테이블 조회만 흉내 내는 읽기 전용 커서."""

    def __init__(self, tables, awards=None, limits=None, levels=None, capped=False, missing_column=None):
        self.tables = set(tables)
        self.awards = awards if awards is not None else list(required_award_types())
        self.limits = limits if limits is not None else list(REQUIRED_LIMITS)
        self.levels = levels if levels is not None else {"OVERALL": OVERALL, "SKILL": SKILL}
        self.capped = capped
        self.missing_column = missing_column
        self.sql = []
        self.result = []

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        text = sql.lower()
        assert not any(word in text for word in ("insert", "update ", "delete", "alter", "create", "drop"))
        if "information_schema.tables" in text:
            self.result = [(t,) for t in self.tables]
        elif "information_schema.columns" in text:
            self.result = [
                ("member_xp_history", "history_id"), ("member_xp_history", "created_at"),
                ("comments", "parent_comment_id"), ("comments", "reply_to_comment_id"),
                ("boards", "course_code"), ("boards", "cohort"),
                ("recruits", "details"),
                ("recruit_programs", "meetup_curriculum_version"),
                ("recruit_programs", "meetup_curriculum_items"),
            ]
            if self.missing_column in self.result:
                self.result.remove(self.missing_column)
        elif "from xp_award_policies" in text:
            self.result = [(a,) for a in self.awards]
        elif "from xp_limit_policies" in text:
            self.result = [(k,) for k in self.limits]
        elif "from level_policies" in text:
            self.result = list(self.levels.get(params[0], []))
        elif "pg_constraint" in text:
            self.result = [(1,)] if self.capped else []
        else:
            raise AssertionError(sql)

    def fetchall(self):
        return self.result


ALL_TABLES = set(schema_check.BASE_TABLES) | {
    "xp_award_policies", "member_board_visits", "member_board_visit_events",
    "level_policies", "xp_limit_policies", "recruit_programs",
}


def test_complete_schema_passes_in_order_without_writes():
    cursor = FakeCursor(ALL_TABLES)
    report = check_schema(cursor)
    assert report.ok and report.issues == []
    assert report.checked == ["000·001", "023", "024", "025", "027"]


@pytest.mark.parametrize("column", ["course_code", "cohort"])
def test_missing_board_column_points_to_018(column):
    report = check_schema(FakeCursor(ALL_TABLES, missing_column=("boards", column)))
    assert not report.ok
    assert f"boards.{column}" in report.errors[0].message
    assert "018_course_cohort_boards.sql" in report.errors[0].fix


def test_missing_reply_target_column_points_to_041():
    """답글 대상 컬럼이 없으면(041 미적용) 기동 전에 오류로 알리고 041 파일을 안내한다."""
    report = check_schema(FakeCursor(ALL_TABLES, missing_column=("comments", "reply_to_comment_id")))
    assert not report.ok
    assert "comments.reply_to_comment_id" in report.errors[0].message
    assert "041_comment_reply_target.sql" in report.errors[0].fix
    # 출처도 000·001이 아니라 041로 표시한다(운영 기동 로그에서 원인 파일을 바로 알 수 있게).
    assert report.errors[0].step == "041"
    assert "[오류][041] comments.reply_to_comment_id 컬럼 없음" in "\n".join(report.lines())


@pytest.mark.parametrize("table,column,step", [
    ("recruits", "details", "042"),
    ("recruit_programs", "meetup_curriculum_version", "043"),
    ("recruit_programs", "meetup_curriculum_items", "043"),
])
def test_missing_meetup_column_points_to_migration(table, column, step):
    report = check_schema(FakeCursor(ALL_TABLES, missing_column=(table, column)))
    assert not report.ok
    assert any(i.step == step and f"{table}.{column}" in i.message for i in report.errors)


def test_missing_base_column_keeps_baseline_source():
    """041 외 기본 컬럼의 출처·안내 문구는 기존 그대로다."""
    report = check_schema(FakeCursor(ALL_TABLES, missing_column=("comments", "parent_comment_id")))
    assert not report.ok
    assert report.errors[0].step == "000·001"
    assert report.errors[0].fix == "database/sql/000_baseline_schema.sql·026_baseline_followups.sql 재실행"


def test_missing_027_table_is_error_with_sql_file():
    report = check_schema(FakeCursor(ALL_TABLES - {"xp_limit_policies"}))
    assert not report.ok
    assert any(i.step == "027" and "027_xp_rule_policies.sql" in i.fix for i in report.errors)


@pytest.mark.parametrize("missing", REQUIRED_LIMITS)
def test_each_missing_027_row_is_named(missing):
    report = check_schema(FakeCursor(ALL_TABLES, limits=[k for k in REQUIRED_LIMITS if k != missing]))
    assert [i.message for i in report.errors] == [f"지급 한도 행 {missing} 없음"]


def test_missing_award_row_points_to_its_migration():
    awards = [a for a in required_award_types() if a not in {"POST", "SKILL_QUIZ"}]
    report = check_schema(FakeCursor(ALL_TABLES, awards=awards))
    fixes = {i.message: i.fix for i in report.errors}
    assert "023_xp_award_policies.sql" in fixes["지급 정책 행 POST 없음"]
    assert "027_xp_rule_policies.sql" in fixes["지급 정책 행 SKILL_QUIZ 없음"]


def test_missing_024_is_warning_only():
    report = check_schema(FakeCursor(ALL_TABLES - {"member_board_visits", "member_board_visit_events"}))
    assert report.ok
    assert {i.level for i in report.issues} == {"warning"}


def test_invalid_or_capped_level_policy_is_error():
    report = check_schema(FakeCursor(ALL_TABLES, levels={"OVERALL": [(1, 0), (3, 500)], "SKILL": SKILL}))
    assert any(i.step == "025" for i in report.errors)
    five = OVERALL + [(5, 3000)]
    report = check_schema(FakeCursor(ALL_TABLES, levels={"OVERALL": five, "SKILL": SKILL}, capped=True))
    assert any("상한" in i.message for i in report.errors)


@pytest.mark.parametrize(
    "app_env,override,expected",
    [("production", "", "strict"), ("", "", "strict"), ("development", "", "warn"),
     ("test", "", "off"), ("production", "warn", "warn"), ("development", "strict", "strict")],
)
def test_check_mode(monkeypatch, app_env, override, expected):
    monkeypatch.setenv("APP_ENV", app_env) if app_env else monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("PLAYMATE_SCHEMA_CHECK", override)
    assert schema_check.check_mode() == expected


def test_strict_startup_blocks_on_missing_policy(monkeypatch):
    monkeypatch.setenv("PLAYMATE_SCHEMA_CHECK", "strict")
    monkeypatch.setattr(schema_check, "run_check",
                        lambda: check_schema(FakeCursor(ALL_TABLES - {"xp_limit_policies"})))
    with pytest.raises(RuntimeError, match="xp_limit_policies"):
        schema_check.startup_check()


def test_warn_startup_reports_without_blocking(monkeypatch):
    monkeypatch.setenv("PLAYMATE_SCHEMA_CHECK", "warn")
    monkeypatch.setattr(schema_check, "run_check",
                        lambda: check_schema(FakeCursor(ALL_TABLES - {"xp_limit_policies"})))
    assert schema_check.startup_check() == {"status": "error", "errors": 1, "warnings": 0}


def test_strict_startup_blocks_when_db_unreachable(monkeypatch):
    monkeypatch.setenv("PLAYMATE_SCHEMA_CHECK", "strict")

    def unreachable():
        raise OSError("connection refused")

    monkeypatch.setattr(schema_check, "run_check", unreachable)
    with pytest.raises(RuntimeError, match="DB"):
        schema_check.startup_check()
