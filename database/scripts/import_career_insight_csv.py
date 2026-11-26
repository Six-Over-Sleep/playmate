"""채용 인사이트 정제 CSV를 public.job_postings(database/sql/051_job_postings.sql)에 적재한다.

기본 실행은 dry-run이며 DB에 연결하지 않는다.
- --preview-db: 읽기 전용 트랜잭션으로 신규·기존 중복·URL 충돌·출처 코드 불일치 건수와 예상 최종 건수를 보여 준다.
- --apply --expected-rows N: 한 트랜잭션으로 **신규 행만** INSERT한다. 실패하면 전체 롤백한다.

적재 정책
- 기존 행은 절대 수정하지 않는다: INSERT ... ON CONFLICT (source, source_id) DO NOTHING.
- 같은 (source, source_id)가 이미 있으면 같은 공고로 보고 건너뛴다(기존 보존).
- 다음은 "모호한 충돌"로 보고 **적재 전체를 중단**한다(자동으로 건너뛰거나 기존 행을 고치지 않는다).
    1. 같은 URL인데 PK가 다른 기존 행 (url UNIQUE 위반 예정)
    2. 사람인 출처 코드 불일치: CSV saramin_web 공고와 같은 ID가 DB에 다른 사람인 코드(saramin)로 있음
    3. 정규화 URL이 같은 다른 PK: 사람인은 rec_idx, 그 밖의 출처는 추적 파라미터를 뺀 주소로 비교
  원본 URL은 바꾸지 않고 그대로 저장한다. 정규화는 충돌 감지에만 쓴다.
- certifications·preferences는 job_postings에 컬럼이 없고 정제 CSV에서 전부 빈 배열이라 저장하지 않는다.
  값이 들어 있는 행이 있으면 정보 손실을 막기 위해 CSV 검증 단계에서 거부한다.

실행 기록(manifest)과 복구
- --apply는 이번 실행에서 실제로 INSERT한 행의 (source, source_id, xmin)과 트랜잭션 시각(updated_at = now())을
  manifest JSON(버전 2)에 남긴다. 커밋 전에 'pending'으로 쓰고, 커밋 후 'committed'로 바꾼다.
- 소유권 판별: 출처·ID·updated_at·xmin이 **모두** 기록과 같은 행만 "이번 실행이 넣고 그 뒤 아무도 고치지 않은 행"으로 본다.
  PostgreSQL은 UPDATE마다 새 행 버전을 만들어 xmin이 바뀐다. 그래서 updated_at을 건드리지 않은 수정도 걸러진다.
- --rollback-manifest PATH: 위 네 조건을 DELETE 문 자체에도 걸어, 대조 이후에 다른 트랜잭션이 고친 행도 지우지 않는다.
  커밋이 증명된 기록(committed·mixed 판정)만 지우고, 판정이 불명확하거나 기록이 손상·불완전하거나
  ROLLBACK_MAX_AGE보다 오래된 기록은 자동 롤백하지 않는다(보류).
- --reconcile-manifest PATH: pending·commit_unknown 기록을 실제 DB와 대조해 커밋 여부를 판정한다(DB는 읽기만 한다).
  --apply를 붙이면 판정이 명확할 때만 manifest 파일의 상태를 committed / not_committed로 고친다.
- 모든 모드는 기본 dry-run(DB 미접속)이고, --preview-db는 읽기 전용, --apply일 때만 쓴다.

xmin의 한계 (그래서 "보조 검증"으로만 쓰고, 맞지 않으면 항상 지우지 않는 쪽으로 판단한다)
- xmin은 32비트 트랜잭션 ID라 약 20억 트랜잭션 뒤에는 같은 값이 다시 나올 수 있다. 오래된 기록은 자동 롤백하지 않는다.
- 덤프·복원, 논리 복제, 테이블 재작성(VACUUM FULL 등)은 xmin을 바꾼다. 이 경우 "변경됨"으로 보고 지우지 않는다(안전한 쪽).
- xmin이 같아도 updated_at·키가 다르면 지우지 않는다. 네 값이 모두 같을 때만 지운다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'public'                # 테스트는 전용 스키마로 바꿔 공용 public을 건드리지 않는다
TABLE_NAME = 'job_postings'
# develop의 job_postings 적재기(database/scripts/import_saramin_jobs.py)와 같은 잠금 키: 두 적재가 겹치지 않게 직렬화한다.
LOCK_KEY = 740_014_020
BATCH_SIZE = 500
SOURCES = ('saramin_web', 'itchaeyong', 'jobkorea')
SARAMIN_CODES = ('saramin', 'saramin_web')   # 같은 사람인 공고를 가리킬 수 있는 출처 코드
ARRAY_COLUMNS = ('job_roles', 'specialties', 'tech_stacks')
DROPPED_EMPTY = ('certifications', 'preferences')   # CSV에는 있으나 job_postings에 없음 (전부 빈 배열이어야 함)
INSERT_COLUMNS = ('source', 'source_id', 'title', 'company', 'url', *ARRAY_COLUMNS, 'raw_tags',
                  'role_classification_source', 'detail_status', 'collected_at', 'collection_year', 'collection_quarter')
CSV_COLUMNS = (*INSERT_COLUMNS, *DROPPED_EMPTY)
# 실제 테이블이 051과 같은지 확인하는 기대 자료형 (information_schema.columns.udt_name)
EXPECTED_TYPES = {'source': 'text', 'source_id': 'text', 'title': 'text', 'company': 'text', 'url': 'text',
                  'job_roles': '_text', 'specialties': '_text', 'tech_stacks': '_text', 'raw_tags': 'jsonb',
                  'role_classification_source': 'text', 'detail_status': 'text', 'collected_at': 'timestamptz',
                  'collection_year': 'int4', 'collection_quarter': 'int4', 'updated_at': 'timestamptz'}
TRACKING_PARAMS = re.compile(r'^(utm_.*|adsCategoryItem|view_type|ref|referrer|fbclid|gclid)$', re.I)
KST = timezone(timedelta(hours=9))
DEFAULT_MANIFEST_DIR = ROOT / 'data' / 'insights_import' / 'import_runs'   # Git 추적 제외 폴더
MANIFEST_VERSION = 2                       # 2: 키마다 xmin 기록 (1은 xmin이 없어 자동 롤백 근거가 부족하므로 거부)
ROLLBACK_MAX_AGE = timedelta(days=7)       # 이보다 오래된 기록은 자동 롤백하지 않는다 (수동 확인)


class ImportAbort(RuntimeError):
    """적재·복구 전제 조건이 맞지 않아 중단한다. 호출 측 트랜잭션은 롤백된다."""


def table() -> str:
    return f'{SCHEMA}.{TABLE_NAME}'


# ---------------------------------------------------------------- URL 정규화 (충돌 감지 전용)
def saramin_rec_idx(url: str) -> str | None:
    parts = urlsplit(url)
    if (parts.hostname or '').lower() not in ('www.saramin.co.kr', 'saramin.co.kr'):
        return None
    values = [v for k, v in parse_qsl(parts.query, keep_blank_values=True) if k == 'rec_idx']
    return values[0] if len(values) == 1 and values[0].isdigit() else None


def normalized_url(url: str) -> str:
    """같은 공고를 가리키는 URL을 같은 문자열로 만든다. 저장값이 아니라 비교 키다."""
    rec = saramin_rec_idx(url)
    if rec is not None:
        return f'saramin:rec_idx={rec}'
    parts = urlsplit(url.strip())
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)))
    path = parts.path.rstrip('/') or '/'
    return urlunsplit(((parts.scheme or 'https').lower(), (parts.hostname or '').lower(), path, query, ''))


# ---------------------------------------------------------------- CSV 검증
def _array(value, name, line):
    try:
        items = json.loads(value or '[]')
    except json.JSONDecodeError as exc:
        raise ValueError(f'{line}행 {name}: JSON 배열이 아닙니다') from exc
    if not isinstance(items, list) or any(not isinstance(v, str) or not v.strip() for v in items):
        raise ValueError(f'{line}행 {name}: 빈 값 없는 문자열 배열이어야 합니다')
    return list(dict.fromkeys(v.strip() for v in items))


def validate_row(raw: dict, line: int) -> dict:
    source = (raw.get('source') or '').strip()
    if source not in SOURCES:
        raise ValueError(f'{line}행: 허용되지 않은 출처 {source!r}')
    source_id = (raw.get('source_id') or '').strip()
    if not source_id or ':' in source_id:
        raise ValueError(f'{line}행: source_id가 비었거나 접두어(:)가 붙어 있습니다 (원본 ID만 허용)')
    title, url = (raw.get('title') or '').strip(), (raw.get('url') or '').strip()
    if not title:
        raise ValueError(f'{line}행: 제목이 없습니다')
    if urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).hostname:
        raise ValueError(f'{line}행: URL이 올바르지 않습니다')
    if source == 'saramin_web':
        if not source_id.isdigit():
            raise ValueError(f'{line}행: 사람인 source_id는 숫자여야 합니다')
        if saramin_rec_idx(url) != source_id:
            raise ValueError(f'{line}행: 사람인 URL의 rec_idx가 source_id와 다릅니다')
    if source == 'itchaeyong' and normalized_url(url) != f'https://itchaeyong.com/jobs/{source_id}':
        raise ValueError(f'{line}행: IT 채용 레이더 URL이 source_id와 다릅니다')
    try:
        collected = datetime.fromisoformat(raw['collected_at'])
        year, quarter = int(raw['collection_year']), int(raw['collection_quarter'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'{line}행: 수집 시각·연도·분기 형식 오류') from exc
    if collected.tzinfo is None:
        raise ValueError(f'{line}행: collected_at에 시간대가 필요합니다 (TIMESTAMPTZ)')
    local = collected.astimezone(KST)
    if (year, quarter) != (local.year, (local.month - 1) // 3 + 1):
        raise ValueError(f'{line}행: 수집 분기가 collected_at(KST)과 다릅니다')
    for name in DROPPED_EMPTY:
        if _array(raw.get(name), name, line):
            raise ValueError(f'{line}행 {name}: job_postings에 저장할 컬럼이 없는데 값이 있습니다 (정보 손실 방지)')
    try:
        raw_tags = json.loads(raw.get('raw_tags') or '[]')
    except json.JSONDecodeError as exc:
        raise ValueError(f'{line}행 raw_tags: JSON이 아닙니다') from exc
    if not isinstance(raw_tags, list):
        raise ValueError(f'{line}행 raw_tags: JSON 배열이어야 합니다')
    row = dict(source=source, source_id=source_id, title=title, company=(raw.get('company') or '').strip() or None,
               url=url, raw_tags=raw_tags,
               role_classification_source=(raw.get('role_classification_source') or '').strip() or None,
               detail_status=(raw.get('detail_status') or '').strip() or None,
               collected_at=collected, collection_year=year, collection_quarter=quarter)
    for name in ARRAY_COLUMNS:
        row[name] = _array(raw.get(name), name, line)
    if not row['job_roles']:
        raise ValueError(f'{line}행: 직무(job_roles)가 비어 있습니다')
    return row


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        missing = set(CSV_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'CSV 필수 컬럼 누락: {sorted(missing)}')
        rows = [validate_row(raw, line) for line, raw in enumerate(reader, 2)]
    for label, key in (('(source, source_id)', lambda r: (r['source'], r['source_id'])), ('URL', lambda r: r['url']),
                       ('정규화 URL', lambda r: normalized_url(r['url']))):
        counts = Counter(key(r) for r in rows)
        duplicated = [k for k, n in counts.items() if n > 1]
        if duplicated:
            raise ValueError(f'CSV 안에 같은 {label}가 중복됩니다: {duplicated[:3]}')
    return rows


# ---------------------------------------------------------------- 충돌 분류 (DB 조회 결과로 계산하는 순수 함수)
@dataclass
class Plan:
    total: int = 0
    by_source: dict = field(default_factory=dict)
    table_rows_before: int | None = None
    new_rows: list = field(default_factory=list)
    existing_pk: list = field(default_factory=list)        # 같은 (source, source_id): 기존 보존, 건너뜀
    url_conflicts: list = field(default_factory=list)      # 같은 URL, 다른 PK                 -> 중단
    source_mismatch: list = field(default_factory=list)    # saramin_web <-> saramin 같은 ID   -> 중단
    normalized_conflicts: list = field(default_factory=list)   # 정규화 URL 같음, 다른 PK      -> 중단
    inserted_keys: list = field(default_factory=list)
    transaction_time: datetime | None = None

    @property
    def new(self) -> int:
        return len(self.new_rows)

    @property
    def blocked(self) -> int:
        return len(self.url_conflicts) + len(self.source_mismatch) + len(self.normalized_conflicts)

    @property
    def expected_total(self) -> int | None:
        return None if self.table_rows_before is None else self.table_rows_before + self.new


def classify(rows: list[dict], existing: list[tuple[str, str, str]], table_rows_before: int | None = None) -> Plan:
    """existing = DB의 (source, source_id, url). 행마다 하나의 범주에만 넣는다 (기존 PK가 가장 우선)."""
    plan = Plan(total=len(rows), by_source=dict(Counter(r['source'] for r in rows)), table_rows_before=table_rows_before)
    pks = {(s, i) for s, i, _ in existing}
    by_url = {u: (s, i) for s, i, u in existing}
    by_norm: dict[str, set] = {}
    for s, i, u in existing:
        by_norm.setdefault(normalized_url(u), set()).add((s, i))
    for r in rows:
        key = (r['source'], r['source_id'])
        if key in pks:
            plan.existing_pk.append(key)
            continue
        if r['url'] in by_url:
            plan.url_conflicts.append((key, by_url[r['url']]))
            continue
        if r['source'] in SARAMIN_CODES:
            alias = next(((code, r['source_id']) for code in SARAMIN_CODES if (code, r['source_id']) in pks), None)
            if alias:
                plan.source_mismatch.append((key, alias))
                continue
        other = by_norm.get(normalized_url(r['url']), set()) - {key}
        if other:
            plan.normalized_conflicts.append((key, sorted(other)[0]))
            continue
        plan.new_rows.append(r)
    return plan


# ---------------------------------------------------------------- DB 공통
def _first(row):
    if row is None:
        return None
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def _tuple(row, *names):
    return tuple(row[n] for n in names) if isinstance(row, dict) else tuple(row)


def check_schema(cursor) -> None:
    """실제 테이블이 051 구조와 같은지 확인한다. 다르면 아무것도 쓰지 않고 중단한다."""
    cursor.execute('SELECT to_regclass(%s) AS name', (table(),))
    if _first(cursor.fetchone()) is None:
        raise ImportAbort(f'{table()} 테이블이 없습니다. 051 마이그레이션을 먼저 확인하세요')
    cursor.execute("""SELECT column_name, udt_name FROM information_schema.columns
                       WHERE table_schema = %s AND table_name = %s""", (SCHEMA, TABLE_NAME))
    actual = dict(_tuple(r, 'column_name', 'udt_name') for r in cursor.fetchall())
    wrong = {k: actual.get(k) for k, v in EXPECTED_TYPES.items() if actual.get(k) != v}
    if wrong:
        raise ImportAbort(f'{table()} 컬럼·자료형이 051과 다릅니다: {wrong}')
    cursor.execute("""SELECT con.contype, array_agg(a.attname ORDER BY a.attname) AS cols
                        FROM pg_constraint con
                        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)
                       WHERE con.conrelid = %s::regclass AND con.contype IN ('p', 'u')
                       GROUP BY con.oid, con.contype""", (table(),))
    constraints = {(_tuple(r, 'contype', 'cols')[0], tuple(_tuple(r, 'contype', 'cols')[1])) for r in cursor.fetchall()}
    if ('p', ('source', 'source_id')) not in constraints:
        raise ImportAbort(f'{table()} 기본키가 (source, source_id)가 아닙니다: {sorted(constraints)}')
    if ('u', ('url',)) not in constraints:
        raise ImportAbort(f'{table()}에 url UNIQUE 제약이 없습니다: {sorted(constraints)}')


def _lock(cursor) -> None:
    cursor.execute("SET LOCAL lock_timeout = '5s'")
    cursor.execute("SET LOCAL statement_timeout = '120s'")
    cursor.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))


def build_plan(cursor, rows: list[dict]) -> Plan:
    cursor.execute(f'SELECT count(*) FROM {table()}')
    total = _first(cursor.fetchone())
    ids = sorted({r['source_id'] for r in rows})
    urls = [r['url'] for r in rows]
    rec_ids = sorted({r['source_id'] for r in rows if r['source'] in SARAMIN_CODES})
    # 비교에 필요한 기존 행만 읽는다: 같은 ID, 같은 URL, 같은 사람인 rec_idx를 가진 사람인 URL
    cursor.execute(f"""SELECT source, source_id, url FROM {table()}
                        WHERE source_id = ANY(%(ids)s) OR url = ANY(%(urls)s)
                           OR (url LIKE '%%saramin.co.kr%%' AND substring(url FROM 'rec_idx=([0-9]+)') = ANY(%(recs)s))""",
                   {'ids': ids, 'urls': urls, 'recs': rec_ids})
    existing = [_tuple(r, 'source', 'source_id', 'url') for r in cursor.fetchall()]
    if any(r['source'] == 'itchaeyong' for r in rows):
        # IT 채용 레이더는 경로로 정규화하므로 같은 호스트의 기존 URL도 함께 본다 (추적 파라미터만 다른 경우)
        cursor.execute(f"SELECT source, source_id, url FROM {table()} WHERE url LIKE %s", ('%itchaeyong.com/jobs/%',))
        existing += [_tuple(r, 'source', 'source_id', 'url') for r in cursor.fetchall()]
    return classify(rows, list(dict.fromkeys(existing)), total)


def preview(cursor, rows: list[dict]) -> Plan:
    cursor.execute('SET TRANSACTION READ ONLY')
    check_schema(cursor)
    return build_plan(cursor, rows)


def _blocked_message(plan: Plan) -> str:
    return (f'모호한 충돌이 있어 적재하지 않습니다: URL 중복 {len(plan.url_conflicts)}건, '
            f'출처 코드 불일치 {len(plan.source_mismatch)}건, 정규화 URL 충돌 {len(plan.normalized_conflicts)}건. '
            f'--preview-db로 확인한 뒤 담당자와 정리하세요 (예: {(plan.url_conflicts + plan.source_mismatch + plan.normalized_conflicts)[:3]})')


def apply(cursor, rows: list[dict], expected_rows: int) -> Plan:
    """신규 행만 INSERT한다. 커밋은 호출 측이 하며, 예외가 나면 호출 측이 롤백해야 한다."""
    from psycopg2.extras import Json, execute_values

    if len(rows) != expected_rows:
        raise ImportAbort(f'CSV 행 수 {len(rows)}건이 --expected-rows {expected_rows}와 다릅니다')
    _lock(cursor)
    check_schema(cursor)
    plan = build_plan(cursor, rows)
    if plan.blocked:
        raise ImportAbort(_blocked_message(plan))
    cursor.execute('SELECT now()')
    plan.transaction_time = _first(cursor.fetchone())
    if plan.new_rows:
        values = [dict(r, raw_tags=Json(r['raw_tags'])) for r in plan.new_rows]
        casts = {c: '::text[]' for c in ARRAY_COLUMNS} | {'raw_tags': '::jsonb'}
        template = '(' + ', '.join(f'%({c})s{casts.get(c, "")}' for c in INSERT_COLUMNS) + ', now())'
        sql = (f'INSERT INTO {table()} ({", ".join(INSERT_COLUMNS)}, updated_at) VALUES %s '
               'ON CONFLICT (source, source_id) DO NOTHING RETURNING source, source_id, xmin::text AS xmin')
        returned = execute_values(cursor, sql, values, template=template, page_size=BATCH_SIZE, fetch=True)
        plan.inserted_keys = [_tuple(r, 'source', 'source_id', 'xmin') for r in returned]
        if len({k[2] for k in plan.inserted_keys}) > 1:
            raise ImportAbort('한 트랜잭션에서 넣은 행의 xmin이 서로 다릅니다 (예상하지 못한 상황): 적재하지 않습니다')
    if len(plan.inserted_keys) != plan.new:
        raise ImportAbort(f'예상 신규 {plan.new}건과 실제 INSERT {len(plan.inserted_keys)}건이 다릅니다 (동시 적재 의심)')
    cursor.execute(f"""SELECT count(*) FROM {table()} t
                        JOIN unnest(%s::text[], %s::text[]) AS k(source, source_id)
                          ON t.source = k.source AND t.source_id = k.source_id""",
                   ([r['source'] for r in rows], [r['source_id'] for r in rows]))
    if _first(cursor.fetchone()) != plan.new + len(plan.existing_pk):
        raise ImportAbort('적재 후 검증 실패: CSV 키 수와 DB 키 수가 맞지 않습니다')
    return plan


# ---------------------------------------------------------------- 실행 기록·복구
RECOVERABLE = ('committed', 'commit_unknown', 'pending')


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def new_manifest(csv_path: Path, digest: str, plan: Plan) -> dict:
    return dict(manifest_version=MANIFEST_VERSION, run_id=uuid.uuid4().hex, table=table(), status='pending',
                csv=csv_path.name, csv_sha256=digest, created_at=datetime.now(timezone.utc).isoformat(),
                transaction_time=plan.transaction_time.isoformat() if plan.transaction_time else None,
                ownership=['source', 'source_id', 'updated_at', 'xmin'],
                total=plan.total, inserted=len(plan.inserted_keys), preserved=len(plan.existing_pk),
                inserted_keys=[list(k) for k in plan.inserted_keys])


def load_manifest(path: Path) -> dict:
    """기록이 손상·불완전하면 ValueError. 추정으로 메우지 않는다 (지울 근거가 없으면 지우지 않는다)."""
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('manifest_version') != MANIFEST_VERSION:
        raise ValueError(f'manifest 버전이 {MANIFEST_VERSION}이 아닙니다 (xmin 기록이 없는 기록은 자동 복구하지 않음)')
    if data.get('table') != table() or not data.get('transaction_time') or not data.get('created_at'):
        raise ValueError('manifest 형식이 올바르지 않거나 대상 테이블이 다릅니다')
    keys = data.get('inserted_keys')
    if not isinstance(keys, list) or any(
            not isinstance(k, list) or len(k) != 3 or not all(isinstance(v, str) and v for v in k) or not k[2].isdigit()
            for k in keys):
        raise ValueError('manifest 키 형식이 올바르지 않습니다 ([source, source_id, xmin])')
    if data.get('inserted') != len(keys) or len({(k[0], k[1]) for k in keys}) != len(keys):
        raise ValueError('manifest 키 수가 기록된 INSERT 건수와 다르거나 중복됩니다 (기록 불완전)')
    if len({k[2] for k in keys}) > 1:
        raise ValueError('manifest의 xmin이 서로 다릅니다 (한 트랜잭션 기록이 아님)')
    try:
        datetime.fromisoformat(data['transaction_time'])
        created = datetime.fromisoformat(data['created_at'])
    except ValueError as exc:
        raise ValueError('manifest 시각 형식 오류') from exc
    if created.tzinfo is None:
        raise ValueError('manifest created_at에 시간대가 없습니다')
    if data.get('status') not in RECOVERABLE:
        raise ValueError(f"복구 대상이 아닌 manifest 상태입니다: {data.get('status')} ({', '.join(RECOVERABLE)}만 가능)")
    return data


def manifest_age(manifest: dict, now: datetime | None = None) -> timedelta:
    return (now or datetime.now(timezone.utc)) - datetime.fromisoformat(manifest['created_at'])


@dataclass
class Reconcile:
    manifest_rows: int = 0
    matching: list = field(default_factory=list)   # 출처·ID·updated_at·xmin 모두 일치 = 이번 실행이 넣고 아무도 안 고친 행
    changed: list = field(default_factory=list)    # 키는 있으나 updated_at 또는 xmin이 다름 = 이후 변경됨 -> 보존
    missing: list = field(default_factory=list)    # 없음 = 커밋되지 않았거나 이미 지워짐 -> 할 일 없음
    deleted: int = 0

    @property
    def verdict(self) -> str:
        """committed/mixed: 일치 행이 있으므로 커밋이 증명됨. unknown: 남은 행이 모두 바뀌어 커밋을 증명할 수 없음 -> 보류."""
        if self.manifest_rows == 0:
            return 'empty'
        if self.matching:
            return 'mixed' if self.missing else 'committed'
        if len(self.missing) == self.manifest_rows:
            return 'not_committed'
        return 'unknown'


def reconcile(cursor, manifest: dict) -> Reconcile:
    """manifest의 키를 실제 DB와 대조한다. updated_at = 이번 트랜잭션 now()이고 xmin이 기록과 같은 행만 이번 실행 행이다.

    이번 실행 전에 있던 행은 RETURNING에 나오지 않으므로 manifest에 없고, 같은 키라도 updated_at·xmin이 달라 일치하지 않는다.
    """
    keys = [tuple(k) for k in manifest['inserted_keys']]
    when = datetime.fromisoformat(manifest['transaction_time'])
    result = Reconcile(manifest_rows=len(keys))
    if not keys:
        return result
    cursor.execute(f"""SELECT t.source, t.source_id, t.updated_at, t.xmin::text AS xmin FROM {table()} t
                        JOIN unnest(%s::text[], %s::text[]) AS k(source, source_id)
                          ON t.source = k.source AND t.source_id = k.source_id""",
                   ([k[0] for k in keys], [k[1] for k in keys]))
    found = {(s, i): (u, x) for s, i, u, x in (_tuple(r, 'source', 'source_id', 'updated_at', 'xmin') for r in cursor.fetchall())}
    for source, source_id, xmin in keys:
        key = (source, source_id)
        if key not in found:
            result.missing.append(key)
        elif found[key] == (when, xmin):
            result.matching.append((source, source_id, xmin))
        else:
            result.changed.append(key)
    return result


def reconcile_preview(cursor, manifest: dict) -> Reconcile:
    cursor.execute('SET TRANSACTION READ ONLY')
    check_schema(cursor)
    return reconcile(cursor, manifest)


def rollback_apply(cursor, manifest: dict, expected_rows: int) -> Reconcile:
    _lock(cursor)
    check_schema(cursor)
    result = reconcile(cursor, manifest)
    if result.verdict not in ('committed', 'mixed'):
        raise ImportAbort(f'판정 {result.verdict}: 커밋이 증명된 이번 실행 행이 없어 삭제하지 않습니다(보류). '
                          '--reconcile-manifest로 상태를 확인하세요')
    if len(result.matching) != expected_rows:
        raise ImportAbort(f'삭제 대상 {len(result.matching)}건이 --expected-rows {expected_rows}와 다릅니다')
    when = datetime.fromisoformat(manifest['transaction_time'])
    # 대조(SELECT)만 믿지 않는다: DELETE 자체에 출처·ID·updated_at·xmin을 모두 건다.
    # 대조 뒤에 다른 트랜잭션이 행을 고쳤다면 새 버전의 xmin이 달라 이 DELETE에 걸리지 않고, 건수 불일치로 전체 롤백된다.
    cursor.execute(f"""DELETE FROM {table()} t
                        USING unnest(%s::text[], %s::text[], %s::text[]) AS k(source, source_id, xmin)
                        WHERE t.source = k.source AND t.source_id = k.source_id
                          AND t.updated_at = %s AND t.xmin::text = k.xmin
                        RETURNING t.source_id""",
                   ([k[0] for k in result.matching], [k[1] for k in result.matching], [k[2] for k in result.matching], when))
    result.deleted = len(cursor.fetchall())
    if result.deleted != expected_rows:
        raise ImportAbort(f'삭제 {result.deleted}건이 예상 {expected_rows}건과 다릅니다 (대조 뒤 변경 의심): 전체 롤백')
    return result


# ---------------------------------------------------------------- CLI
def _print_plan(plan: Plan, mode: str) -> None:
    print(f'[{mode}] CSV 전체 {plan.total}건 / 출처별 {plan.by_source}')
    print(f'  기존 DB 행 수 {plan.table_rows_before}건 -> 예상 최종 {plan.expected_total}건')
    print(f'  신규 적재 가능 {plan.new}건 / 기존 PK 중복(건너뜀) {len(plan.existing_pk)}건')
    print(f'  URL 중복 {len(plan.url_conflicts)}건 / 출처 코드 불일치 {len(plan.source_mismatch)}건 / '
          f'정규화 URL 충돌 {len(plan.normalized_conflicts)}건')
    if plan.blocked:
        print('  ! 모호한 충돌이 있어 --apply는 중단됩니다. 예시(키만): '
              f'{[k for k, _ in (plan.url_conflicts + plan.source_mismatch + plan.normalized_conflicts)[:5]]}')


def _print_reconcile(result: Reconcile, mode: str) -> None:
    print(f'[{mode}] manifest 키 {result.manifest_rows}건 / 삭제 가능(4개 조건 일치) {len(result.matching)}건 / '
          f'이후 변경되어 보존 {len(result.changed)}건 / DB에 없음 {len(result.missing)}건 / 판정 {result.verdict}')
    if result.deleted:
        print(f'  삭제 {result.deleted}건 / 보존 {len(result.changed)}건 / 처리 대상 아님(없음) {len(result.missing)}건')


@contextmanager
def _default_cursor(commit: bool):
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core.db_connect import db_cursor
    with db_cursor(commit=commit) as cursor:
        yield cursor


def _is_commit_unknown(exc: BaseException) -> bool:
    return type(exc).__name__ == 'CommitOutcomeUnknownError'


def _manifest_mode(args, cursor_factory) -> int:
    path = args.rollback_manifest or args.reconcile_manifest
    try:
        manifest = load_manifest(path)
    except (OSError, ValueError) as exc:
        print(f'manifest 확인 실패: {exc}')
        return 2
    age = manifest_age(manifest)
    print(f"manifest {path.name} / run {manifest['run_id']} / 상태 {manifest['status']} / "
          f"INSERT 키 {len(manifest['inserted_keys'])}건 / 트랜잭션 시각 {manifest['transaction_time']} / 경과 {age}")
    if not (args.preview_db or args.apply):
        print('dry-run: DB에 연결하지 않았습니다. 대조는 --preview-db, 실행은 --apply')
        return 0
    if args.rollback_manifest and args.apply and (age > ROLLBACK_MAX_AGE or age < timedelta(0)):
        print(f'기록 시각이 {ROLLBACK_MAX_AGE}보다 오래됐거나 미래입니다: 자동 롤백하지 않습니다(보류). '
              '--preview-db로 대조한 뒤 담당자와 수동으로 처리하세요.')
        return 2
    if args.reconcile_manifest:
        with cursor_factory(commit=False) as cursor:   # 대조는 항상 읽기 전용 (--apply는 파일만 고친다)
            result = reconcile_preview(cursor, manifest)
        _print_reconcile(result, 'reconcile')
        if args.apply:
            if result.verdict not in ('committed', 'not_committed'):
                print('  판정이 명확하지 않아 manifest를 고치지 않았습니다. 사람이 확인하세요.')
                return 2
            manifest.update(status=result.verdict, reconciled_at=datetime.now(timezone.utc).isoformat(),
                            reconciled_from=manifest['status'])
            write_json_atomic(path, manifest)
            print(f'  manifest 상태를 {result.verdict}로 기록했습니다 (DB 변경 없음)')
        return 0
    try:
        with cursor_factory(commit=args.apply) as cursor:
            result = rollback_apply(cursor, manifest, args.expected_rows) if args.apply else reconcile_preview(cursor, manifest)
    except ImportAbort as exc:
        print(f'중단(롤백): {exc}')
        return 2
    _print_reconcile(result, 'rollback apply' if args.apply else 'rollback preview')
    if args.apply:
        manifest.update(status='reverted', reverted_at=datetime.now(timezone.utc).isoformat(), reverted_rows=result.deleted,
                        reverted_from=manifest['status'], reverted_preserved_changed=[list(k) for k in result.changed],
                        reverted_missing=[list(k) for k in result.missing])
        write_json_atomic(path, manifest)
        print(f'  DELETE {result.deleted}건 커밋 완료 (manifest 상태 reverted)')
    return 0


def main(argv=None, cursor_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv', type=Path, nargs='?', help='적재할 정제 CSV')
    parser.add_argument('--rollback-manifest', type=Path, help='이 manifest로 INSERT한 행만 되돌림')
    parser.add_argument('--reconcile-manifest', type=Path, help='pending·commit_unknown 기록을 실제 DB와 대조')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--preview-db', action='store_true', help='읽기 전용으로 건수 확인')
    mode.add_argument('--apply', action='store_true', help='실제 쓰기 (기본은 dry-run)')
    parser.add_argument('--expected-rows', type=int, help='적재: CSV 행 수 / 되돌리기: 삭제 대상 수 (--apply 시 필수)')
    parser.add_argument('--manifest-dir', type=Path, help=f'실행 기록 저장 폴더 (기본: {DEFAULT_MANIFEST_DIR.relative_to(ROOT)})')
    args = parser.parse_args(argv)
    if sum(x is not None for x in (args.csv, args.rollback_manifest, args.reconcile_manifest)) != 1:
        parser.error('CSV 경로, --rollback-manifest, --reconcile-manifest 중 하나만 지정하세요')
    if args.apply and args.expected_rows is None and not args.reconcile_manifest:
        parser.error('--apply에는 --expected-rows가 필요합니다')
    cursor_factory = cursor_factory or _default_cursor

    if args.rollback_manifest or args.reconcile_manifest:
        return _manifest_mode(args, cursor_factory)

    try:
        rows = read_rows(args.csv)
    except (OSError, ValueError) as exc:
        print(f'CSV 검증 실패: {exc}')
        return 2
    digest = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    print(f'CSV {args.csv.name} SHA256 {digest[:16]}… / 유효 {len(rows)}건 / 출처별 {dict(Counter(r["source"] for r in rows))}')
    print(f'  대상 {table()} / 저장하지 않는 빈 컬럼 {", ".join(DROPPED_EMPTY)}')
    if not (args.preview_db or args.apply):
        print('dry-run: DB에 연결하지 않았습니다. 확인은 --preview-db, 적재는 --apply --expected-rows N')
        return 0
    if args.preview_db:
        try:
            with cursor_factory(commit=False) as cursor:
                plan = preview(cursor, rows)
        except ImportAbort as exc:
            print(f'중단: {exc}')
            return 2
        _print_plan(plan, 'preview')
        return 0

    manifest_dir = args.manifest_dir or DEFAULT_MANIFEST_DIR
    manifest_path, manifest = None, None
    try:
        with cursor_factory(commit=True) as cursor:
            plan = apply(cursor, rows, args.expected_rows)
            # 커밋 직전에 기록: 커밋 결과가 불분명해도 이번 실행 키를 잃지 않는다 (pending은 --reconcile-manifest로 판정).
            manifest = new_manifest(args.csv, digest, plan)
            manifest_path = manifest_dir / f"insight_import_{manifest['run_id']}.json"
            write_json_atomic(manifest_path, manifest)
    except ImportAbort as exc:
        print(f'중단(롤백): {exc}')
        return 2
    except BaseException as exc:
        if manifest_path:
            manifest['status'] = 'commit_unknown' if _is_commit_unknown(exc) else 'rolled_back'
            try:
                write_json_atomic(manifest_path, manifest)
                print(f"실행 기록 {manifest_path} 상태 {manifest['status']}")
            except OSError:
                print(f'실행 기록 갱신 실패: {manifest_path}는 pending으로 남습니다. --reconcile-manifest로 판정하세요.')
        raise
    manifest['status'] = 'committed'
    try:
        write_json_atomic(manifest_path, manifest)
    except OSError:
        print(f'커밋은 완료됐지만 실행 기록을 committed로 바꾸지 못했습니다: {manifest_path} (pending). '
              '--reconcile-manifest로 판정하세요.')
        _print_plan(plan, 'apply')
        return 3
    _print_plan(plan, 'apply')
    print(f'  INSERT {len(plan.inserted_keys)}건 커밋 완료 / 실행 기록 {manifest_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
