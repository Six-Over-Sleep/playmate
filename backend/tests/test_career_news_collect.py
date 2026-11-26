"""커리어 브리핑 뉴스 RSS 수집 → 저장 스크립트(database/scripts/collect_career_news.py)를 네트워크·DB 없이 확인한다.

분야별 실패 처리, 종료 코드, 크롤러 분야 검사, 크롤러 폴더 불러오기를 검사한다.
PLAYMATE_CAREER_CRAWLER_DIR에 career_news_crawler 폴더를 주면 실제 크롤러 코드에 고정 RSS 응답을 넣어
수집·필터 결과가 저장용 뉴스로 바뀌는지도 확인한다. (외부 요청 없음)
PostgreSQL 저장은 tests/integration/test_postgres_career_news_collect.py에서 일회용 DB로 확인한다.
"""
import importlib.util
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "collect_career_news", ROOT / "database" / "scripts" / "collect_career_news.py"
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

CRAWLER_DIR = os.getenv("PLAYMATE_CAREER_CRAWLER_DIR")


def categories():
    """크롤러 config.CATEGORIES와 같은 모양. 분야마다 검색어 2개."""
    return {
        name: {"code": code, "queries": [f"{code}-q1", f"{code}-q2"], "title_keywords": [name]}
        for name, code in collector.FIELD_CODES.items()
    }


def fake_collect(failing_queries=(), per_query=1):
    """검색어별로 기사 per_query건을 돌려준다. failing_queries는 네트워크 오류를 낸다."""
    calls = []

    def collect(query, title_keywords, days, session=None):
        calls.append((query, days))
        if query in failing_queries:
            raise ConnectionError(f"{query} 연결 실패")
        return [
            {
                "title": f"{query} 기사 {index}",
                "source": "테스트신문",
                "link": f"https://news.google.com/rss/articles/{query}-{index}?oc=5",
                "published": "2026-10-30T00:00:00+00:00",
            }
            for index in range(per_query)
        ]

    collect.calls = calls
    return collect


def no_db():
    raise AssertionError("확인 모드에서는 DB에 연결하면 안 됩니다")


def test_check_categories_requires_same_eight_fields():
    collector.check_categories(categories())

    renamed = categories()
    renamed["AI"] = renamed.pop("데이터·AI")
    with pytest.raises(ValueError):
        collector.check_categories(renamed)

    recoded = categories()
    recoded["정보보안"]["code"] = "sec"
    with pytest.raises(ValueError):
        collector.check_categories(recoded)

    missing = categories()
    missing.pop("QA·테스트")
    with pytest.raises(ValueError):
        collector.check_categories(missing)


def test_collect_all_skips_failed_queries_and_marks_failed_fields():
    collect = fake_collect(failing_queries={"backend-q1", "security-q1", "security-q2"})
    logs = []
    rows, results = collector.collect_all(categories(), collect, days=7, log=logs.append)

    by_code = {result.code: result for result in results}
    assert len(collect.calls) == 16 and {days for _, days in collect.calls} == {7}
    assert by_code["backend"].succeeded_queries == 1 and not by_code["backend"].failed  # 검색어 1개 실패는 분야 성공
    assert by_code["security"].failed and by_code["security"].articles == 0             # 검색어 전부 실패
    assert [code for code, *_ in rows].count("security") == 0
    assert len(rows) == 13
    assert any("정보보안" in line and "기존 뉴스 유지" in line for line in logs)
    assert any("security-q1: ConnectionError" in line for line in logs)


def test_collect_all_pauses_between_queries_only(monkeypatch):
    sleeps = []
    monkeypatch.setattr(collector.time, "sleep", sleeps.append)
    collector.collect_all(categories(), fake_collect(), days=7, pause=0.5, log=lambda _: None)
    assert sleeps == [0.5] * 15


def test_same_link_in_two_fields_becomes_one_news():
    shared = {"title": "AI 보안 위협 증가", "source": "테스트신문",
              "link": "https://news.google.com/rss/articles/SHARED?oc=5", "published": None}

    def collect(query, title_keywords, days, session=None):
        return [shared] if query in ("data_ai-q1", "security-q2") else []

    rows, _ = collector.collect_all(categories(), collect, days=7, log=lambda _: None)
    articles, _ = collector.build_articles(rows)
    assert len(articles) == 1
    assert articles[0].field_codes == {"data_ai", "security"}
    assert articles[0].link_type == "GOOGLE_NEWS_RSS"


def test_dry_run_reports_without_database():
    logs = []
    code = collector.main(["--pause", "0"], collector=(categories(), fake_collect()), cursor_factory=no_db, log=logs.append)
    assert code == collector.EXIT_OK
    assert any("확인 모드" in line for line in logs)
    assert any("GOOGLE_NEWS_RSS 16건" in line for line in logs)


def test_exit_codes_for_partial_and_total_failure():
    partial = fake_collect(failing_queries={"mobile-q1", "mobile-q2"})
    assert collector.main(["--pause", "0"], collector=(categories(), partial), cursor_factory=no_db,
                          log=lambda _: None) == collector.EXIT_PARTIAL

    every_query = {f"{code}-q{index}" for code in collector.FIELD_CODES.values() for index in (1, 2)}
    logs = []
    code = collector.main(["--apply", "--pause", "0"], collector=(categories(), fake_collect(every_query)),
                          cursor_factory=no_db, log=logs.append)
    assert code == collector.EXIT_NOTHING_SAVED  # DB에 연결하지 않는다
    assert any("DB를 변경하지 않았습니다" in line for line in logs)

    empty = fake_collect(per_query=0)  # 검색은 성공했지만 관련 기사가 없음
    assert collector.main(["--apply", "--pause", "0"], collector=(categories(), empty), cursor_factory=no_db,
                          log=lambda _: None) == collector.EXIT_NOTHING_SAVED


def test_apply_saves_only_collected_fields(monkeypatch):
    saved = {}

    def import_articles(cursor, articles, seen_at):
        saved["articles"] = articles
        saved["seen_at"] = seen_at
        return sys.modules["import_career_news"].ImportReport(inserted=len(articles))

    monkeypatch.setattr(collector, "import_articles", import_articles)
    monkeypatch.setattr(collector, "field_freshness", lambda cursor: [])

    @contextmanager
    def cursor_factory():
        yield object()

    code = collector.main(["--apply", "--pause", "0"],
                          collector=(categories(), fake_collect(failing_queries={"qa_test-q1", "qa_test-q2"})),
                          cursor_factory=cursor_factory, log=lambda _: None)
    assert code == collector.EXIT_PARTIAL
    codes = set().union(*(article.field_codes for article in saved["articles"]))
    assert codes == set(collector.FIELD_CODES.values()) - {"qa_test"}
    assert saved["seen_at"].tzinfo is None  # career_news는 UTC naive TIMESTAMP


@pytest.mark.parametrize("argv", [["--days", "0"], ["--days", "31"], ["--pause", "-1"]])
def test_invalid_arguments(argv):
    with pytest.raises(SystemExit):
        collector.main(argv, collector=(categories(), fake_collect()), cursor_factory=no_db, log=lambda _: None)


@pytest.fixture
def isolated_imports(monkeypatch):
    """크롤러의 config·src 모듈이 다른 테스트에 남지 않도록 sys.path·sys.modules를 되돌린다."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in [name for name in sys.modules if name in ("config", "src") or name.startswith("src.")]:
        monkeypatch.delitem(sys.modules, name)
    yield
    for name in [name for name in sys.modules if name in ("config", "src") or name.startswith("src.")]:
        del sys.modules[name]


def write_fake_crawler(base: Path, codes: dict) -> Path:
    (base / "src").mkdir(parents=True)
    (base / "src" / "__init__.py").write_text("", encoding="utf-8")
    (base / "config.py").write_text(
        "CATEGORIES = {" + ", ".join(
            f"{name!r}: {{'code': {code!r}, 'queries': ['q'], 'title_keywords': ['k']}}" for name, code in codes.items()
        ) + "}\n",
        encoding="utf-8",
    )
    (base / "src" / "rss_collector.py").write_text(
        "def collect_google_news(query, title_keywords, days=14, limit=30, session=None):\n    return []\n",
        encoding="utf-8",
    )
    return base


def test_load_crawler_from_folder(tmp_path, isolated_imports):
    categories_, collect = collector.load_crawler(write_fake_crawler(tmp_path / "crawler", collector.FIELD_CODES))
    assert {spec["code"] for spec in categories_.values()} == set(collector.FIELD_CODES.values())
    assert collect("q", ["k"], days=1) == []


def test_load_crawler_rejects_missing_files_and_other_fields(tmp_path, isolated_imports):
    with pytest.raises(FileNotFoundError):
        collector.load_crawler(tmp_path / "없는 폴더")
    other = write_fake_crawler(tmp_path / "other", {"데이터·AI": "data_ai"})
    with pytest.raises(ValueError):
        collector.load_crawler(other)


def test_load_crawler_rejects_module_from_another_folder(tmp_path, isolated_imports):
    first = write_fake_crawler(tmp_path / "first", collector.FIELD_CODES)
    collector.load_crawler(first)
    second = write_fake_crawler(tmp_path / "second", collector.FIELD_CODES)
    with pytest.raises(ImportError):
        collector.load_crawler(second)  # 이미 불러온 first의 config를 second 것으로 착각하지 않는다


def google_rss(items) -> bytes:
    body = "".join(
        f"<item><title>{title} - {source}</title><link>{link}</link>"
        f"<pubDate>{format_datetime(published)}</pubDate>"
        f'<source url="https://example.com">{source}</source></item>'
        for title, source, link, published in items
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'.encode()


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class FakeSession:
    """Google News RSS 대신 고정 응답을 돌려준다. 검색어 'FAIL'이 들어간 요청은 오류를 낸다."""

    def __init__(self, content):
        self.content = content
        self.urls = []

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        if "FAIL" in url:
            raise ConnectionError("요청 실패")
        return FakeResponse(self.content)


@pytest.mark.skipif(not CRAWLER_DIR, reason="PLAYMATE_CAREER_CRAWLER_DIR에 career_news_crawler 폴더를 줄 때만 실행")
def test_real_crawler_code_with_fixed_rss(isolated_imports):
    categories_, collect = collector.load_crawler(Path(CRAWLER_DIR))
    now = datetime.now(timezone.utc)
    rss = google_rss([
        ("생성형 AI 보안 위협 증가", "보안신문", "https://news.google.com/rss/articles/CBMiA1?oc=5", now - timedelta(days=1)),
        ("국비지원 교육 AI 수강생 모집", "홍보신문", "https://news.google.com/rss/articles/CBMiA2?oc=5", now - timedelta(days=1)),
        ("오래된 클라우드 기사", "IT신문", "https://news.google.com/rss/articles/CBMiA3?oc=5", now - timedelta(days=40)),
        ("쿠버네티스 인프라 운영 사례", "IT신문", "https://news.google.com/rss/articles/CBMiA4?oc=5", now - timedelta(days=2)),
    ])
    session = FakeSession(rss)
    categories_ = dict(categories_)
    categories_["모바일 개발"] = dict(categories_["모바일 개발"], queries=["FAIL 모바일"])

    rows, results = collector.collect_all(categories_, collect, days=14, session=session, log=lambda _: None)
    articles, skipped = collector.build_articles(rows)

    assert all("news.google.com/rss/search" in url and "when%3A14d" in url for url in session.urls)
    by_code = {result.code: result for result in results}
    assert by_code["mobile"].failed and not by_code["data_ai"].failed
    by_title = {article.title: article for article in articles}
    assert set(by_title) == {"생성형 AI 보안 위협 증가", "쿠버네티스 인프라 운영 사례"}  # 제외어·기간 필터는 크롤러 기준
    assert {"data_ai", "security"} <= by_title["생성형 AI 보안 위협 증가"].field_codes
    assert "cloud_infra" in by_title["쿠버네티스 인프라 운영 사례"].field_codes
    assert by_title["생성형 AI 보안 위협 증가"].source_name == "보안신문"
    assert by_title["생성형 AI 보안 위협 증가"].link_url == "https://news.google.com/rss/articles/CBMiA1"
    assert all(article.link_type == "GOOGLE_NEWS_RSS" for article in articles)
    assert not skipped
