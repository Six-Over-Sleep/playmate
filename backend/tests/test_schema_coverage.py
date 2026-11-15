"""코드가 쓰는 테이블·컬럼의 DDL이 저장소 마이그레이션(database/sql)에 있는지 확인한다.

000_baseline_schema.sql 이전에는 members·posts 등 16개 테이블과 comments.parent_comment_id가
공유 DB에만 있어 저장소만으로 새 환경을 만들 수 없었다. DB에 접속하지 않는다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "database" / "sql"
APP = ROOT / "backend" / "app"

# SQL 문맥이 아닌 대문자 단어·CTE 이름 등
NOT_TABLES = {
    "target", "claimed", "personal", "daily", "likes", "skills", "set", "generate_series",
    "latest", "ranked", "counts", "visible", "base", "recent", "totals", "member_counts",
    "scraps", "news", "items", "lateral", "unnest", "values",
}


def _migration_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(SQL_DIR.glob("*.sql")))


def _created_tables(text: str) -> set[str]:
    return {name.lower() for name in re.findall(
        r"CREATE TABLE(?: IF NOT EXISTS)?\s+(?:public\.)?(\w+)", text, re.IGNORECASE)}


def _tables_used_by_code() -> set[str]:
    used = set()
    for path in APP.rglob("*.py"):
        for block in re.findall(r'"""(.*?)"""', path.read_text(encoding="utf-8"), re.S):
            # 같은 SQL 안에서 정의한 CTE(WITH x AS / WITH RECURSIVE x(..) AS / , x AS)는 테이블이 아니다.
            ctes = set(re.findall(
                r"(?:\bWITH(?:\s+RECURSIVE)?|,)\s+([a-z_]+)\s*(?:\([^)]*\))?\s+AS\s*\(", block))
            names = re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(?:public\.)?([a-z_]+)\b", block)
            used.update(name.lower() for name in names if name not in ctes)
    # PostgreSQL 시스템 카탈로그(pg_*)는 마이그레이션 대상이 아니다.
    return {name for name in used if not name.startswith("pg_")} - NOT_TABLES


def test_baseline_runs_before_other_migrations():
    names = sorted(path.name for path in SQL_DIR.glob("*.sql"))
    assert names[0] == "000_baseline_schema.sql"


def test_every_table_used_in_sql_is_created_by_a_migration():
    missing = _tables_used_by_code() - _created_tables(_migration_text())
    assert not missing, f"database/sql에 CREATE TABLE이 없는 테이블: {sorted(missing)}"


def test_comment_reply_column_has_ddl():
    text = _migration_text()
    assert "ADD COLUMN IF NOT EXISTS parent_comment_id" in text
    assert "fk_comments_parent" in text


def test_level_upper_bound_is_owned_by_level_policies():
    text = (SQL_DIR / "025_level_policies.sql").read_text(encoding="utf-8")
    assert "DROP CONSTRAINT IF EXISTS member_levels_level_check" in text
    assert "CHECK (level >= 1)" in text
