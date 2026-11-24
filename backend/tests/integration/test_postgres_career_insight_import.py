"""채용 인사이트 CSV 적재·대조·되돌리기를 실제 PostgreSQL(job_postings, 051 구조)에서 검증한다.

**사용자가 승인해 준비한 전용 테스트 DB에서만 실행한다.** (공용·운영 DB와 다른 프로젝트 컨테이너 사용 금지)
실행 조건 (하나라도 어기면 skip 또는 fail, DB를 바꾸기 전에 확인):
  1. PLAYMATE_CAREER_INSIGHT_TEST_ALLOW=1
  2. PLAYMATE_CAREER_INSIGHT_TEST_DB_URL=postgresql://<user>:<pw>@127.0.0.1:<port>/playmate_insight_test
     - 호스트는 127.0.0.1/localhost만, DB 이름은 playmate_insight_test만
     - URL 쿼리의 host·hostaddr·service·port, 환경변수 PGHOST·PGHOSTADDR·PGSERVICE·PGSERVICEFILE·PGOPTIONS 금지 (접속 우회)
  3. 접속 뒤 current_database() = playmate_insight_test
  4. DB 주석(식별 마커) = 'playmate-insight-import-test-only'  — 테스트 DB를 만든 사람이 미리 설정한다:
       COMMENT ON DATABASE playmate_insight_test IS 'playmate-insight-import-test-only';
  5. public에 업무 테이블(members, posts, job_postings 등)이 있으면 중단 (공용 DB 복사본일 수 있음)
적재·되돌리기 테스트는 public을 건드리지 않는다: 전용 스키마 career_insight_test만 만들고 지우며, 적재 스크립트의 SCHEMA를 그 스키마로 바꿔 실행한다.
예외: 실제 FastAPI HTTP 테스트 1건은 라우터가 public.job_postings를 직접 읽으므로, 위 확인을 통과한 일회용 DB의 public에
develop 051 구조 job_postings 하나만 만들고(업무 테이블이 하나라도 있으면 중단) 끝나면 자신이 만든 그 테이블만 DROP한다.
051_job_postings.sql이 이 브랜치에 없으면 아래 DDL_051 사본을 쓴다 (develop 5f7e174와 주석·공백 외 동일함을 확인함).
develop 라우터 호환 검사는 git으로 develop의 실제 소스를 메모리에 읽어 실행한다 (없으면 '미검증'으로 skip).
"""
import csv
import importlib.util
import json
import os
import subprocess
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

DB_URL = os.getenv("PLAYMATE_CAREER_INSIGHT_TEST_DB_URL")
ALLOWED = os.getenv("PLAYMATE_CAREER_INSIGHT_TEST_ALLOW") == "1"
pytestmark = pytest.mark.skipif(not (DB_URL and ALLOWED),
                                reason="승인된 전용 테스트 DB에서만 실행 (ALLOW=1과 DB URL 필요)")

TEST_DB_NAME = "playmate_insight_test"
MARKER = "playmate-insight-import-test-only"
BUSINESS_TABLES = ("members", "posts", "comments", "boards", "notifications", "career", "job_postings",
                   "saramin_insight_jobs", "post_reactions", "recruits")
BYPASS_ENV = ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")
ROOT = Path(__file__).resolve().parents[3]
MIGRATION_051 = ROOT / "database" / "sql" / "051_job_postings.sql"
REAL_CSV = ROOT / "data" / "insights_import" / "cleaned_v3" / "final_load_saramin_insight_jobs.csv"
DEVELOP_REF = os.getenv("PLAYMATE_DEVELOP_REF", "origin/develop")
SPEC = importlib.util.spec_from_file_location(
    "import_career_insight_csv", ROOT / "database" / "scripts" / "import_career_insight_csv.py"
)
importer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = importer  # dataclass가 모듈을 조회할 수 있게 등록
SPEC.loader.exec_module(importer)
SCHEMA = "career_insight_test"
assert SCHEMA != "public"

# develop(5f7e174) database/sql/051_job_postings.sql 사본 (파일이 있으면 파일을 우선 사용)
DDL_051 = """
CREATE TABLE IF NOT EXISTS public.job_postings (
    source_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'saramin',
    title TEXT NOT NULL,
    company TEXT,
    url TEXT NOT NULL,
    job_roles TEXT[] NOT NULL DEFAULT '{}',
    specialties TEXT[] NOT NULL DEFAULT '{}',
    tech_stacks TEXT[] NOT NULL DEFAULT '{}',
    raw_tags JSONB,
    role_classification_source TEXT,
    detail_status TEXT,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collection_year INTEGER,
    collection_quarter INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_job_postings PRIMARY KEY (source, source_id),
    CONSTRAINT ck_job_postings_quarter CHECK (collection_quarter BETWEEN 1 AND 4),
    CONSTRAINT uq_job_postings_url UNIQUE (url)
);
CREATE INDEX IF NOT EXISTS idx_job_postings_quarter ON public.job_postings (collection_year, collection_quarter);
CREATE INDEX IF NOT EXISTS idx_job_postings_roles ON public.job_postings USING GIN (job_roles);
CREATE INDEX IF NOT EXISTS idx_job_postings_specialties ON public.job_postings USING GIN (specialties);
CREATE INDEX IF NOT EXISTS idx_job_postings_stacks ON public.job_postings USING GIN (tech_stacks);
"""
SARAMIN = "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=list&rec_idx={}"


# ------------------------------------------------------------------ 전용 테스트 DB 확인 (DB를 바꾸기 전에)
def verify_test_database(url: str) -> None:
    parts = urlsplit(url)
    problems = []
    if parts.scheme not in ("postgresql", "postgres"):
        problems.append("URL 형식은 postgresql://만 허용")
    if parts.hostname not in ("127.0.0.1", "localhost"):
        problems.append(f"호스트 {parts.hostname!r}: 127.0.0.1/localhost만 허용")
    if parts.path.lstrip("/") != TEST_DB_NAME:
        problems.append(f"DB 이름은 {TEST_DB_NAME}만 허용")
    bypass = {"host", "hostaddr", "service", "port"} & set(parse_qs(parts.query))
    if bypass:
        problems.append(f"URL 쿼리의 접속 우회 설정 금지: {sorted(bypass)}")
    env = [name for name in BYPASS_ENV if os.environ.get(name)]
    if env:
        problems.append(f"접속 대상을 바꿀 수 있는 환경변수 금지: {env}")
    if problems:
        pytest.fail("전용 테스트 DB 조건 불충족: " + "; ".join(problems))
    conn = psycopg2.connect(url)
    try:
        conn.set_session(readonly=True, autocommit=True)    # 확인 단계는 읽기만 한다
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database(), shobj_description(oid, 'pg_database') "
                           "FROM pg_database WHERE datname = current_database()")
            name, comment = cursor.fetchone()
            cursor.execute("SELECT table_name FROM information_schema.tables "
                           "WHERE table_schema = 'public' AND table_name = ANY(%s)", (list(BUSINESS_TABLES),))
            business = sorted(r[0] for r in cursor.fetchall())
    finally:
        conn.close()
    if name != TEST_DB_NAME:
        pytest.fail(f"실제 접속 DB가 {name!r}입니다 ({TEST_DB_NAME}만 허용)")
    if comment != MARKER:
        pytest.fail(f"식별 마커가 없습니다. 테스트 DB를 만든 뒤 COMMENT ON DATABASE {TEST_DB_NAME} IS '{MARKER}';")
    if business:
        pytest.fail(f"public에 업무 테이블이 있어 중단합니다 (공용 DB 복사본 의심): {business}")


@pytest.fixture(scope="session")
def verified_db():
    verify_test_database(DB_URL)
    return DB_URL


@pytest.fixture
def connection(verified_db, monkeypatch):
    monkeypatch.setattr(importer, "SCHEMA", SCHEMA)          # public 대신 전용 스키마
    ddl = MIGRATION_051.read_text(encoding="utf-8") if MIGRATION_051.exists() else DDL_051
    conn = psycopg2.connect(verified_db)
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")   # 전용 스키마만 (public 아님)
        cursor.execute(f"CREATE SCHEMA {SCHEMA}")
        cursor.execute(ddl.replace("public.job_postings", f"{SCHEMA}.job_postings"))
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.close()


def cursor_factory_for(conn):
    """db_cursor(commit=...)와 같은 의미: 정상 종료 시 commit 또는 rollback, 예외 시 rollback."""
    @contextmanager
    def make(commit):
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
            conn.commit() if commit else conn.rollback()
        except BaseException:
            conn.rollback()
            raise
    return make


@pytest.fixture
def factory(connection):
    return cursor_factory_for(connection)


class CommitOutcomeUnknownError(RuntimeError):
    """backend db_connect의 같은 이름 예외를 흉내 낸다 (적재 스크립트는 클래스 이름으로 판별)."""


def csv_rows(count):
    rows = []
    for i in range(count):
        if i % 3 == 0:
            source, sid, url = "saramin_web", str(1000 + i), SARAMIN.format(1000 + i)
        else:
            source, sid = "itchaeyong", f"id-{i}"
            url = f"https://itchaeyong.com/jobs/{sid}"
        rows.append({
            "source_id": sid, "source": source, "title": f"공고 {i}", "company": "회사" if i % 2 else "", "url": url,
            "job_roles": json.dumps(["백엔드"]), "specialties": json.dumps(["클라우드"] if i % 4 == 0 else []),
            "tech_stacks": json.dumps(["Python", "AWS"]), "certifications": "[]", "preferences": "[]",
            "raw_tags": json.dumps([f"태그 {i}"]), "role_classification_source": "tag", "detail_status": "listing_page",
            "collected_at": "2026-11-20T00:00:00+09:00", "collection_year": "2026", "collection_quarter": "4",
        })
    return rows


def write_csv(tmp_path, rows):
    path = tmp_path / "load.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def seed(conn, source, sid, url, title="기존 행"):
    with conn.cursor() as cursor:
        cursor.execute(f"""INSERT INTO {SCHEMA}.job_postings (source, source_id, title, url, collection_year, collection_quarter,
                                  updated_at) VALUES (%s, %s, %s, %s, 2026, 4, '2026-10-01T00:00:00+09:00')""",
                       (source, sid, title, url))
    conn.commit()


def count(conn, where="TRUE", params=None):
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {SCHEMA}.job_postings WHERE {where}", params)
        return cursor.fetchone()[0]


def run(tmp_path, factory, path, expected, *extra):
    code = importer.main([str(path), "--apply", "--expected-rows", str(expected), "--manifest-dir", str(tmp_path / "runs"),
                          *extra], cursor_factory=factory)
    return code, *latest_manifest(tmp_path)


def latest_manifest(tmp_path):
    files = sorted((tmp_path / "runs").glob("*.json"), key=lambda p: p.stat().st_mtime) if (tmp_path / "runs").exists() else []
    return (json.loads(files[-1].read_text(encoding="utf-8")) if files else None), files


def rollback(path, factory, expected):
    return importer.main(["--rollback-manifest", str(path), "--apply", "--expected-rows", str(expected)], cursor_factory=factory)


# ------------------------------------------------------------------ 적재
def test_apply_into_empty_table(connection, factory, tmp_path):
    code, manifest, _ = run(tmp_path, factory, write_csv(tmp_path, csv_rows(30)), 30)
    assert code == 0 and manifest["status"] == "committed" and manifest["inserted"] == 30
    assert count(connection) == 30
    assert count(connection, "source = 'itchaeyong' AND source_id LIKE 'id-%%'", ()) == 20, "접두어 없이 원본 ID로 저장"
    with connection.cursor() as cursor:
        cursor.execute(f"""SELECT raw_tags, jsonb_typeof(raw_tags), tech_stacks, specialties, company, collected_at, updated_at,
                                  xmin::text FROM {SCHEMA}.job_postings WHERE source = 'itchaeyong' AND source_id = 'id-1'""")
        raw, kind, tech, spec, company, collected, updated, xmin = cursor.fetchone()
    assert (raw, kind, tech, spec, company) == (["태그 1"], "array", ["Python", "AWS"], [], "회사")
    assert collected.utcoffset() is not None and updated.isoformat() == manifest["transaction_time"]
    assert {k[2] for k in manifest["inserted_keys"]} == {xmin}, "manifest에 실제 행 버전(xmin) 기록"


def test_real_cleaned_csv_2095_rows(connection, factory, tmp_path):
    if not REAL_CSV.exists():
        pytest.skip("로컬 정제 CSV가 없음 (Git 제외 데이터)")
    code, manifest, _ = run(tmp_path, factory, REAL_CSV, 2095)
    assert code == 0 and (manifest["inserted"], manifest["preserved"]) == (2095, 0)
    assert count(connection) == 2095
    assert count(connection, "source = 'saramin_web'") == 490 and count(connection, "source = 'itchaeyong'") == 1605
    assert count(connection, "jsonb_typeof(raw_tags) = 'array'") == 2095


def test_existing_pk_is_preserved_not_overwritten(connection, factory, tmp_path):
    seed(connection, "saramin_web", "1000", SARAMIN.format(1000))
    code, manifest, _ = run(tmp_path, factory, write_csv(tmp_path, csv_rows(30)), 30)
    assert (code, manifest["inserted"], manifest["preserved"]) == (0, 29, 1)
    assert all(k[:2] != ["saramin_web", "1000"] for k in manifest["inserted_keys"])
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT title FROM {SCHEMA}.job_postings WHERE source = 'saramin_web' AND source_id = '1000'")
        assert cursor.fetchone()[0] == "기존 행"


def test_rerun_inserts_nothing(connection, factory, tmp_path):
    path = write_csv(tmp_path, csv_rows(30))
    run(tmp_path, factory, path, 30)
    code, manifest, files = run(tmp_path, factory, path, 30)
    assert (code, manifest["inserted"], manifest["preserved"], len(files)) == (0, 0, 30, 2)
    assert count(connection) == 30


@pytest.mark.parametrize("existing, reported", [
    (("itchaeyong", "other", SARAMIN.format(1000)), "URL 중복 1건"),                                # 같은 URL, 다른 PK
    (("saramin", "1000", "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1000"), "출처 코드 불일치 1건"),
    (("saramin_web", "777", SARAMIN.format(1000) + "&adsCategoryItem=effect_bold"), "정규화 URL 충돌 1건"),
])
def test_ambiguous_conflicts_abort_everything(connection, factory, tmp_path, capsys, existing, reported):
    seed(connection, *existing)
    code, manifest, _ = run(tmp_path, factory, write_csv(tmp_path, csv_rows(30)), 30)
    out = capsys.readouterr().out
    assert code == 2 and manifest is None and "모호한 충돌" in out
    assert count(connection) == 1, "한 건도 넣지 않음"
    assert importer.main([str(write_csv(tmp_path, csv_rows(30))), "--preview-db"], cursor_factory=factory) == 0
    preview = capsys.readouterr().out
    assert reported in preview and "신규 적재 가능 29건" in preview


def test_failure_mid_insert_rolls_back_everything(connection, tmp_path):
    rows = importer.read_rows(write_csv(tmp_path, csv_rows(1200)))
    rows[1100]["collection_quarter"] = 9                     # CHECK 위반: 마지막 배치에서 실패
    with pytest.raises(psycopg2.errors.CheckViolation):
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            importer.apply(cursor, rows, expected_rows=len(rows))
    connection.rollback()
    assert count(connection) == 0


def test_expected_rows_mismatch_aborts(connection, factory, tmp_path):
    code, manifest, _ = run(tmp_path, factory, write_csv(tmp_path, csv_rows(10)), 11)
    assert code == 2 and manifest is None and count(connection) == 0


def test_preview_is_read_only_and_reports_expected_total(connection, factory, tmp_path, capsys):
    seed(connection, "saramin_web", "1000", SARAMIN.format(1000))
    assert importer.main([str(write_csv(tmp_path, csv_rows(30))), "--preview-db"], cursor_factory=factory) == 0
    out = capsys.readouterr().out
    assert "신규 적재 가능 29건" in out and "기존 PK 중복(건너뜀) 1건" in out and "예상 최종 30건" in out
    assert count(connection) == 1


@pytest.mark.parametrize("alter, reported", [
    ("DROP CONSTRAINT uq_job_postings_url", "UNIQUE"),
    ("ALTER COLUMN raw_tags TYPE text USING raw_tags::text", "자료형"),
    ("ALTER COLUMN collected_at TYPE timestamp", "자료형"),
])
def test_schema_mismatch_aborts_before_writing(connection, factory, tmp_path, capsys, alter, reported):
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {SCHEMA}.job_postings {alter}")
    connection.commit()
    code, manifest, _ = run(tmp_path, factory, write_csv(tmp_path, csv_rows(5)), 5)
    assert code == 2 and manifest is None and reported in capsys.readouterr().out
    assert count(connection) == 0


# ------------------------------------------------------------------ 되돌리기 (소유권: 출처·ID·updated_at·xmin)
def test_rollback_deletes_only_rows_inserted_by_that_run(connection, factory, tmp_path, capsys):
    seed(connection, "saramin_web", "1000", SARAMIN.format(1000))             # 적재 전부터 있던 행
    _, manifest, [path] = run(tmp_path, factory, write_csv(tmp_path, csv_rows(30)), 30)
    seed(connection, "itchaeyong", "later", "https://itchaeyong.com/jobs/later")   # 다른 작업이 넣은 행
    with connection.cursor() as cursor:
        # (a) updated_at을 바꾸는 수정, (b) updated_at을 바꾸지 않는 수정 -> 둘 다 보존돼야 한다
        cursor.execute(f"UPDATE {SCHEMA}.job_postings SET title = '수정 a', updated_at = now() + interval '1 second' "
                       "WHERE source = 'itchaeyong' AND source_id = 'id-1'")
        cursor.execute(f"UPDATE {SCHEMA}.job_postings SET title = '수정 b' WHERE source = 'itchaeyong' AND source_id = 'id-2'")
    connection.commit()
    before = count(connection)
    assert rollback(path, factory, 28) == 2 and count(connection) == before, "예상 수가 다르면 아무것도 지우지 않음"
    assert rollback(path, factory, 27) == 0
    assert "삭제 27건 / 보존 2건" in capsys.readouterr().out
    assert count(connection) == before - 27
    for source, sid in (("saramin_web", "1000"), ("itchaeyong", "later"), ("itchaeyong", "id-1"), ("itchaeyong", "id-2")):
        assert count(connection, "source = %s AND source_id = %s", (source, sid)) == 1
    reverted = json.loads(path.read_text(encoding="utf-8"))
    assert (reverted["status"], reverted["reverted_rows"]) == ("reverted", 27)
    assert sorted(reverted["reverted_preserved_changed"]) == [["itchaeyong", "id-1"], ["itchaeyong", "id-2"]]


def test_rows_with_different_xmin_are_never_deleted(connection, factory, tmp_path):
    _, manifest, [path] = run(tmp_path, factory, write_csv(tmp_path, csv_rows(12)), 12)
    other = str(int(manifest["inserted_keys"][0][2]) + 1)
    path.write_text(json.dumps(dict(manifest, inserted_keys=[[s, i, other] for s, i, _ in manifest["inserted_keys"]])),
                    encoding="utf-8")
    assert rollback(path, factory, 12) == 2 and rollback(path, factory, 0) == 2, "판정 unknown: 보류"
    assert count(connection) == 12


def test_delete_itself_rechecks_ownership_after_reconcile(connection, factory, tmp_path, monkeypatch, capsys):
    """대조(SELECT) 뒤 DELETE 전에 다른 트랜잭션이 행을 고치면: DELETE 조건(xmin)에 걸리지 않아 건수 불일치로 전체 롤백."""
    _, manifest, [path] = run(tmp_path, factory, write_csv(tmp_path, csv_rows(12)), 12)
    original = importer.reconcile

    def reconcile_then_concurrent_update(cursor, data):
        result = original(cursor, data)
        other = psycopg2.connect(DB_URL)
        other.autocommit = True
        with other.cursor() as c:                            # updated_at은 그대로, 행 버전만 바뀜
            c.execute(f"UPDATE {SCHEMA}.job_postings SET title = '동시 수정' WHERE source = 'itchaeyong' AND source_id = 'id-1'")
        other.close()
        return result
    monkeypatch.setattr(importer, "reconcile", reconcile_then_concurrent_update)
    assert rollback(path, factory, 12) == 2
    assert "대조 뒤 변경 의심" in capsys.readouterr().out
    assert count(connection) == 12, "아무것도 지우지 않음 (전체 롤백)"


def test_pending_after_commit_is_reconciled_and_recoverable(connection, factory, tmp_path, capsys):
    """커밋은 됐는데 manifest가 pending으로 남은 상황: 실제 DB와 대조해 committed로 판정하고, 되돌리기도 가능하다."""
    seed(connection, "saramin_web", "1000", SARAMIN.format(1000))
    _, manifest, [path] = run(tmp_path, factory, write_csv(tmp_path, csv_rows(12)), 12)
    path.write_text(json.dumps(dict(manifest, status="pending")), encoding="utf-8")   # committed 기록 전에 중단된 것과 같음
    assert importer.main(["--reconcile-manifest", str(path), "--preview-db"], cursor_factory=factory) == 0
    assert "판정 committed" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "pending", "preview는 파일도 고치지 않음"
    assert importer.main(["--reconcile-manifest", str(path), "--apply"], cursor_factory=factory) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "committed"
    path.write_text(json.dumps(dict(manifest, status="pending")), encoding="utf-8")
    assert rollback(path, factory, 11) == 0
    assert count(connection) == 1 and count(connection, "source_id = '1000'") == 1, "기존 행은 남음"


def test_pending_without_proof_is_held(connection, factory, tmp_path, capsys):
    """기록의 키가 DB에 '다른 버전'으로만 있거나 없으면 커밋을 증명할 수 없다: 판정 unknown, 파일·DB 모두 그대로."""
    seed(connection, "saramin_web", "1000", SARAMIN.format(1000))
    path = tmp_path / "pending.json"
    path.write_text(json.dumps({
        "manifest_version": 2, "run_id": "x", "table": f"{SCHEMA}.job_postings", "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(), "transaction_time": datetime.now(timezone.utc).isoformat(),
        "inserted": 2, "inserted_keys": [["saramin_web", "1000", "1"], ["itchaeyong", "id-1", "1"]]}), encoding="utf-8")
    assert importer.main(["--reconcile-manifest", str(path), "--preview-db"], cursor_factory=factory) == 0
    assert "판정 unknown" in capsys.readouterr().out
    assert importer.main(["--reconcile-manifest", str(path), "--apply"], cursor_factory=factory) == 2, "모호하면 파일도 안 고침"
    assert rollback(path, factory, 0) == 2, "보류"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "pending"
    assert count(connection) == 1, "기존 행을 지우지 않음"


def test_commit_unknown_when_commit_happened(connection, tmp_path, capsys):
    @contextmanager
    def commit_then_lost_response(commit):
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            yield cursor
        connection.commit()
        raise CommitOutcomeUnknownError("커밋 응답 유실 모의")
    with pytest.raises(CommitOutcomeUnknownError):
        importer.main([str(write_csv(tmp_path, csv_rows(9))), "--apply", "--expected-rows", "9",
                       "--manifest-dir", str(tmp_path / "runs")], cursor_factory=commit_then_lost_response)
    manifest, [path] = latest_manifest(tmp_path)
    assert manifest["status"] == "commit_unknown" and count(connection) == 9

    @contextmanager
    def plain(commit):
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            yield cursor
        connection.commit() if commit else connection.rollback()
    assert importer.main(["--reconcile-manifest", str(path), "--preview-db"], cursor_factory=plain) == 0
    assert "판정 committed" in capsys.readouterr().out
    assert rollback(path, plain, 9) == 0 and count(connection) == 0


def test_commit_unknown_when_commit_did_not_happen(connection, factory, tmp_path, capsys):
    @contextmanager
    def rollback_then_lost_response(commit):
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            yield cursor
        connection.rollback()
        raise CommitOutcomeUnknownError("커밋 응답 유실 모의 (실제로는 미커밋)")
    with pytest.raises(CommitOutcomeUnknownError):
        importer.main([str(write_csv(tmp_path, csv_rows(9))), "--apply", "--expected-rows", "9",
                       "--manifest-dir", str(tmp_path / "runs")], cursor_factory=rollback_then_lost_response)
    manifest, [path] = latest_manifest(tmp_path)
    assert manifest["status"] == "commit_unknown" and count(connection) == 0
    assert importer.main(["--reconcile-manifest", str(path), "--apply"], cursor_factory=factory) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "not_committed"
    assert rollback(path, factory, 0) == 2, "not_committed 기록은 복구 대상이 아님"


def test_damaged_manifest_deletes_nothing(connection, factory, tmp_path):
    _, manifest, [path] = run(tmp_path, factory, write_csv(tmp_path, csv_rows(12)), 12)
    for broken in ("{not json", json.dumps(dict(manifest, inserted=13)),
                   json.dumps(dict(manifest, inserted_keys=manifest["inserted_keys"][:-1])),
                   json.dumps(dict(manifest, manifest_version=1))):
        path.write_text(broken, encoding="utf-8")
        assert rollback(path, factory, 12) == 2
    path.unlink()
    assert rollback(path, factory, 12) == 2
    assert count(connection) == 12


def test_failure_after_manifest_marks_rolled_back(connection, tmp_path):
    @contextmanager
    def failing_commit(commit):
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            yield cursor
        connection.rollback()
        raise RuntimeError("커밋 실패 모의")
    with pytest.raises(RuntimeError):
        importer.main([str(write_csv(tmp_path, csv_rows(5))), "--apply", "--expected-rows", "5",
                       "--manifest-dir", str(tmp_path / "runs")], cursor_factory=failing_commit)
    manifest, _ = latest_manifest(tmp_path)
    assert manifest["status"] == "rolled_back" and count(connection) == 0


# ------------------------------------------------------------------ develop 라우터 호환 (실제 develop 소스 실행)
def _develop_source(path):
    try:
        out = subprocess.run(["git", "show", f"{DEVELOP_REF}:{path}"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        out = None
    if out is None or out.returncode != 0:
        pytest.skip(f"develop 라우터 미검증: {DEVELOP_REF}:{path}를 읽을 수 없음")
    return out.stdout


def test_develop_router_reads_loaded_rows(connection, factory, tmp_path, monkeypatch):
    """develop의 career_insights.py·career_insight_stats.py 원본을 메모리에서 실행한다 (파일 미생성).

    바꾸는 것은 SQL의 스키마 이름(public -> 전용 테스트 스키마) 하나뿐이다. 그 밖의 SELECT·집계·응답 구성은 develop 코드 그대로다.
    """
    router_src = _develop_source("backend/app/routers/career_insights.py")
    stats_src = _develop_source("backend/app/services/career_insight_stats.py")
    if "public.job_postings" not in router_src:
        pytest.skip("develop 라우터 미검증: develop 라우터가 public.job_postings를 읽지 않음 (구조 변경)")
    stats = types.ModuleType("develop_career_insight_stats")
    stats.__file__ = str(ROOT / "backend" / "app" / "services" / "career_insight_stats.py")   # 모듈 속성 = exec globals
    exec(compile(stats_src, f"{DEVELOP_REF}:career_insight_stats.py", "exec"), stats.__dict__)
    monkeypatch.setitem(sys.modules, "backend.app.services.career_insight_stats", stats)
    router = types.ModuleType("develop_career_insights")
    router.__file__ = str(ROOT / "backend" / "app" / "routers" / "career_insights.py")
    exec(compile(router_src.replace("public.job_postings", f"{SCHEMA}.job_postings"),
                 f"{DEVELOP_REF}:career_insights.py", "exec"), router.__dict__)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    run(tmp_path, factory, write_csv(tmp_path, csv_rows(120)), 120)
    filters = router.filters("db")
    summary = router.summary("db", None, None, None)
    by_field = router.summary("db", None, "클라우드", "Python")
    assert set(filters) >= {"quarters", "fields", "skills", "total"} and filters["total"] == 120
    assert filters["quarters"] == ["2026-Q4"]
    for key in ("count", "total", "roles", "fields", "skills", "coverage", "trend", "certifications", "preferences"):
        assert key in summary
    assert (summary["total"], by_field["count"]) == (120, 30)
    assert summary["coverage"]["certification"] == 0 and summary["coverage"]["preference"] == 0


# ------------------------------------------------------------------ 실제 FastAPI HTTP (정제 CSV → public.job_postings → API)
# develop 라우터의 필터는 specialties·tech_stacks 값과 정확히 같아야 한다 ('AI'가 아니라 'AI(인공지능)').
REAL_FIELD, REAL_SKILL, REAL_QUARTER = "AI(인공지능)", "Python", "2026-Q4"
SUMMARY_KEYS = {"source", "count", "total", "filters", "roles", "fields", "skills", "certifications", "preferences",
                "coverage", "trend", "collected_from", "collected_to"}
RANKED = (("roles", "job_roles"), ("fields", "specialties"), ("skills", "tech_stacks"))


def public_table_exists(cursor):
    cursor.execute("SELECT to_regclass('public.job_postings') IS NOT NULL")
    return cursor.fetchone()[0]


@pytest.fixture
def public_job_postings(verified_db):
    """확인된 일회용 DB의 public에만 develop 051 구조 job_postings를 만들고, 끝나면 자신이 만든 그 테이블만 지운다."""
    if not MIGRATION_051.exists():
        pytest.fail("develop 051 Migration 파일이 없어 HTTP 검증을 중단합니다")
    conn = psycopg2.connect(verified_db)
    conn.autocommit = True
    created = False
    try:
        with conn.cursor() as cursor:
            # 세션 시작 때의 확인과 별개로, 테이블을 만들기 직전에 다시 확인한다 (읽기만)
            cursor.execute("SELECT current_database(), shobj_description(oid, 'pg_database') "
                           "FROM pg_database WHERE datname = current_database()")
            if cursor.fetchone() != (TEST_DB_NAME, MARKER):
                pytest.fail("HTTP 테스트 직전 DB 이름·식별 마커 확인 실패")
            cursor.execute("SELECT table_name FROM information_schema.tables "
                           "WHERE table_schema = 'public' AND table_name = ANY(%s)", (list(BUSINESS_TABLES),))
            business = sorted(r[0] for r in cursor.fetchall())
            if business:
                pytest.fail(f"public에 업무 테이블이 있어 HTTP 테스트를 중단합니다: {business}")
            created = True      # 바로 위에서 부재를 확인했으므로, DDL이 중간에 실패해도 남은 것은 이 테스트가 만든 것이다
            cursor.execute(MIGRATION_051.read_text(encoding="utf-8"))
        yield conn
    finally:
        try:
            if created:
                with conn.cursor() as cursor:
                    cursor.execute("DROP TABLE IF EXISTS public.job_postings")   # public 스키마 자체는 건드리지 않는다
                    assert not public_table_exists(cursor), "public.job_postings 정리 실패"
        finally:
            conn.close()


def sql_expected(conn, quarter=None, field=None, skill=None):
    """API와 독립적으로 public.job_postings를 직접 집계한다 (stats 서비스와 같은 필터 정의: 분기 일치, 배열 포함)."""
    where, params = ["TRUE"], []
    if quarter:
        year, q = quarter.split("-Q")
        where.append("collection_year = %s AND collection_quarter = %s")
        params += [int(year), int(q)]
    if field:
        where.append("%s = ANY(specialties)")
        params.append(field)
    if skill:
        where.append("%s = ANY(tech_stacks)")
        params.append(skill)
    condition = " AND ".join(where)
    trend_condition = " AND ".join(w for w in where if not w.startswith("collection_year"))
    trend_params = [p for p in params if not isinstance(p, int)]
    with conn.cursor() as cursor:
        cursor.execute(f"""SELECT count(*), count(*) FILTER (WHERE cardinality(specialties) > 0),
                                  count(*) FILTER (WHERE cardinality(tech_stacks) > 0)
                           FROM public.job_postings WHERE {condition}""", params)
        total, field_cov, skill_cov = cursor.fetchone()
        ranked = {}
        for key, column in RANKED:
            cursor.execute(f"""SELECT item, count(*) FROM (
                                   SELECT DISTINCT source, source_id, btrim(item) AS item
                                   FROM public.job_postings, unnest({column}) AS item WHERE {condition}) s
                               WHERE item <> '' GROUP BY item""", params)
            ranked[key] = [{"name": n, "count": c} for n, c in sorted(cursor.fetchall(), key=lambda p: (-p[1], p[0]))]
        cursor.execute(f"""SELECT collection_year || '-Q' || collection_quarter, count(*) FROM public.job_postings
                           WHERE {trend_condition or 'TRUE'} GROUP BY 1""", trend_params)
        trend_counts = dict(cursor.fetchall())
        cursor.execute("SELECT DISTINCT collection_year || '-Q' || collection_quarter FROM public.job_postings")
        observed = sorted((r[0] for r in cursor.fetchall()), reverse=True)
    return {"count": total, "coverage": {"field": field_cov, "skill": skill_cov, "certification": 0, "preference": 0},
            "trend": [{"id": q, "count": trend_counts.get(q, 0)} for q in reversed(observed)], **ranked}


def assert_summary_matches(response, conn, total, quarter=None, field=None, skill=None):
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == SUMMARY_KEYS, "develop 라우터 응답 키"
    expected = sql_expected(conn, quarter, field, skill)
    assert (body["source"], body["total"], body["count"]) == ("db", total, expected["count"])
    assert body["filters"] == {"quarter": quarter, "field": field, "skill": skill}
    for key, _ in RANKED:
        assert body[key] == expected[key], f"{key} 집계가 SQL과 다름"
    assert body["coverage"] == expected["coverage"] and body["trend"] == expected["trend"]
    assert body["certifications"] == [] and body["preferences"] == [], "저장하지 않는 빈 컬럼"
    assert body["collected_from"].startswith("2026-11-") and body["collected_from"] <= body["collected_to"]
    return body


def test_http_api_serves_real_csv_loaded_into_public_job_postings(public_job_postings, verified_db, client,
                                                                   monkeypatch, tmp_path):
    """정제 CSV 2,095건 → 실제 적재 스크립트 → public.job_postings → 실제 app.main FastAPI HTTP 응답.

    라우터의 connect()·load_rows()는 바꾸지 않는다. 이 테스트 범위에서만 DATABASE_URL을 일회용 DB로 지정한다.
    """
    if not REAL_CSV.exists():
        pytest.skip("로컬 정제 CSV가 없음 (Git 제외 데이터) — HTTP 검증 미완료")
    from backend.app.routers import career_insights     # app.main이 등록한 바로 그 모듈 (교체하지 않음)

    assert importer.SCHEMA == "public", "운영과 같은 경로: 적재 스크립트 기본 스키마 그대로"
    load_conn = psycopg2.connect(verified_db)
    try:
        code = importer.main([str(REAL_CSV), "--apply", "--expected-rows", "2095", "--manifest-dir", str(tmp_path / "runs")],
                             cursor_factory=cursor_factory_for(load_conn))
    finally:
        load_conn.close()
    manifest, _ = latest_manifest(tmp_path)
    assert code == 0 and manifest["status"] == "committed" and (manifest["inserted"], manifest["preserved"]) == (2095, 0)
    db = public_job_postings
    with db.cursor() as cursor:
        cursor.execute("SELECT source, count(*) FROM public.job_postings GROUP BY source")
        assert dict(cursor.fetchall()) == {"saramin_web": 490, "itchaeyong": 1605}

    base = "/api/career/insights"
    names = ("DATABASE_URL", "POSTGRES_DSN")
    before = {name: os.environ.get(name) for name in names}
    with monkeypatch.context() as env:
        env.setenv("DATABASE_URL", verified_db)
        env.delenv("POSTGRES_DSN", raising=False)
        # 실제 라우터 연결 함수가 일회용 DB로 향하는지 먼저 확인 (공용 DB로 갈 경로 차단 확인)
        with career_insights.connect() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT current_database(), shobj_description(oid, 'pg_database') "
                           "FROM pg_database WHERE datname = current_database()")
            assert tuple(cursor.fetchone().values()) == (TEST_DB_NAME, MARKER)

        filters = client.get(f"{base}/db/filters")
        everything = client.get(f"{base}/db/summary")
        by_quarter = client.get(f"{base}/db/summary", params={"quarter": REAL_QUARTER})
        by_field = client.get(f"{base}/db/summary", params={"field": REAL_FIELD})
        by_skill = client.get(f"{base}/db/summary", params={"skill": REAL_SKILL})
        combined = client.get(f"{base}/db/summary", params={"quarter": REAL_QUARTER, "field": REAL_FIELD, "skill": REAL_SKILL})
        no_field = client.get(f"{base}/db/summary", params={"field": "존재하지 않는 분야"})
        no_skill = client.get(f"{base}/db/summary", params={"skill": "존재하지않는스택"})
        no_quarter = client.get(f"{base}/db/summary", params={"quarter": "2025-Q1"})
        bad_quarter = client.get(f"{base}/db/summary", params={"quarter": "2026-Q5"})
        bad_source = client.get(f"{base}/unknown/summary")
        legacy_filters = client.get(f"{base}/filters")
        legacy_summary = client.get(f"{base}/summary", params={"field": REAL_FIELD, "skill": REAL_SKILL})
    assert {name: os.environ.get(name) for name in names} == before, "환경변수 복원"

    # filters: 실제 SQL과 비교
    assert filters.status_code == 200, filters.text
    with db.cursor() as cursor:
        cursor.execute("SELECT DISTINCT unnest(specialties) FROM public.job_postings")
        fields = sorted(r[0] for r in cursor.fetchall())
        cursor.execute("SELECT DISTINCT unnest(tech_stacks) FROM public.job_postings")
        skills = sorted(r[0] for r in cursor.fetchall())
    assert filters.json() == {"quarters": [REAL_QUARTER], "fields": fields, "skills": skills, "total": 2095}
    assert REAL_FIELD in fields and REAL_SKILL in skills
    assert legacy_filters.status_code == 200 and legacy_filters.json() == filters.json()

    # summary: 응답 전체를 SQL 집계와 비교하고, 오프라인 CSV 검증 수치도 함께 고정
    assert assert_summary_matches(everything, db, 2095)["count"] == 2095
    assert assert_summary_matches(by_quarter, db, 2095, quarter=REAL_QUARTER)["count"] == 2095
    assert assert_summary_matches(by_field, db, 2095, field=REAL_FIELD)["count"] == 222
    assert assert_summary_matches(by_skill, db, 2095, skill=REAL_SKILL)["count"] == 241
    combo = assert_summary_matches(combined, db, 2095, quarter=REAL_QUARTER, field=REAL_FIELD, skill=REAL_SKILL)
    assert combo["count"] == 36 and combo["trend"] == [{"id": REAL_QUARTER, "count": 36}]
    assert legacy_summary.status_code == 200 and legacy_summary.json()["count"] == 36

    # 존재하지 않는 필터: 오류가 아니라 0건
    for response, kwargs in ((no_field, {"field": "존재하지 않는 분야"}), (no_skill, {"skill": "존재하지않는스택"})):
        body = assert_summary_matches(response, db, 2095, **kwargs)
        assert body["count"] == 0 and body["roles"] == [] and body["trend"] == [{"id": REAL_QUARTER, "count": 0}]
    body = assert_summary_matches(no_quarter, db, 2095, quarter="2025-Q1")
    assert body["count"] == 0 and body["trend"] == [{"id": REAL_QUARTER, "count": 2095}]
    assert bad_quarter.status_code == 422, "분기 형식은 라우터 Query pattern이 거부"
    assert bad_source.status_code == 404
