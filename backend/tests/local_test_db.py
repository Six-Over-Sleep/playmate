"""로컬 일회용 PostgreSQL 테스트 DB 안전장치(테스트 수집 대상 아님).

실제 PostgreSQL이 필요한 테스트는 이 함수로 접속 대상을 먼저 검사한다.
환경변수에 주소가 없거나, 로컬(localhost·127.0.0.1·::1)이 아니거나, DB 이름에 test가 없으면
DB에 접속하기 전에 pytest skip으로 건너뛴다. 공용 .env DB 설정은 절대 사용하지 않는다.
"""

import os
from urllib.parse import urlsplit

import pytest

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
LOCAL_TEST_DB_ENV = "PLAYMATE_LOCAL_TEST_DB_URL"


def require_local_test_db_url(env_name: str = LOCAL_TEST_DB_ENV) -> str:
    """연결 전에 테스트 DB 주소를 검사하고, 안전한 경우에만 주소를 반환한다."""
    url = os.getenv(env_name)
    if not url:
        pytest.skip(f"{env_name}에 로컬 일회용 테스트 DB 주소가 있을 때만 실행")
    target = urlsplit(url)
    if target.hostname not in LOCAL_HOSTS:
        pytest.skip("로컬 일회용 DB(127.0.0.1/localhost/::1)에서만 실행")
    if "test" not in target.path.lstrip("/").lower():
        pytest.skip("DB 이름에 test가 포함된 일회용 DB에서만 실행")
    return url


def skip_unless_tables(cursor, *tables: str) -> None:
    """임시 테이블 복제에 필요한 public 테이블이 테스트 DB에 없으면 건너뛴다."""
    for table in tables:
        cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        row = cursor.fetchone()
        value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
        if value is None:
            pytest.skip(f"테스트 DB에 public.{table}가 없습니다(마이그레이션 적용 필요)")
