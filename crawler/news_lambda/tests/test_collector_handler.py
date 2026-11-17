"""Collector Lambda(collector_handler.py) 단위 테스트 — 인터넷·AWS·DB 없이 실행한다.

실행(저장소 루트): python -m unittest discover -s crawler/news_lambda/tests -v

- 외부 접속을 막기 위해 socket 연결·주소 조회를 가로채 실패시키고, 시도가 있었는지 매 테스트 끝에 확인한다.
- S3는 put_object만 흉내 내는 가짜 클라이언트를 넣는다(boto3를 불러오지 않는다).
- 실제 8개 분야(config.CATEGORIES)와 실제 collect_google_news·collect_all을 그대로 쓰고,
  RSS 응답만 고정 XML을 돌려주는 가짜 session으로 바꾼다.
"""

import importlib.util
import json
import socket
import sys
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

HANDLER_PATH = Path(__file__).resolve().parents[1] / "collector_handler.py"
REPO_ROOT = Path(__file__).resolve().parents[3]

_SAVED_PATH = list(sys.path)
_SAVED_MODULES = set(sys.modules)
_NETWORK_ATTEMPTS = []
_PATCHES = []


def _blocked(*args, **kwargs):
    _NETWORK_ATTEMPTS.append(args[:2])
    raise OSError("테스트 중 외부 네트워크 접속 차단")


def setUpModule():
    for target in ("socket.socket.connect", "socket.socket.connect_ex",
                   "socket.create_connection", "socket.getaddrinfo"):
        patcher = mock.patch(target, _blocked)
        patcher.start()
        _PATCHES.append(patcher)


def tearDownModule():
    for patcher in _PATCHES:
        patcher.stop()
    # 크롤러 config/src 등 테스트가 불러온 모듈과 sys.path 변경을 되돌린다.
    for name in set(sys.modules) - _SAVED_MODULES:
        del sys.modules[name]
    sys.path[:] = _SAVED_PATH


def load_handler():
    spec = importlib.util.spec_from_file_location("collector_handler_under_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    # dataclass가 지연 평가 주석을 해석할 때 sys.modules에서 모듈을 찾으므로 먼저 등록한다.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


handler = load_handler()


# -- 가짜 객체 -----------------------------------------------------------------------
class FakeClientError(Exception):
    """botocore ClientError와 같은 response 구조만 흉내 낸다."""

    def __init__(self, code, status):
        super().__init__(f"An error occurred ({code})")
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


class FakeS3:
    """put_object(IfNoneMatch="*" 조건부 쓰기 포함)와 get_object만 흉내 낸다."""

    def __init__(self, status=200, error=None):
        self.calls = []
        self.gets = []
        self.objects = {}
        self.status = status
        self.error = error
        self.get_error = None

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if kwargs.get("IfNoneMatch") == "*" and kwargs["Key"] in self.objects:
            raise FakeClientError("PreconditionFailed", 412)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ResponseMetadata": {"HTTPStatusCode": self.status}, "ETag": '"fake"'}

    def get_object(self, **kwargs):
        import io

        self.gets.append(kwargs)
        if self.get_error is not None:
            raise self.get_error
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}


class FakeContext:
    def __init__(self, request_id="11111111-2222-3333-4444-555555555555", remaining_ms=None):
        self.aws_request_id = request_id
        self._remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self._remaining_ms


class NoTimeLimitContext:
    aws_request_id = "req-local"


class FakeRssSession:
    """collect_google_news가 쓰는 session.get/raise_for_status/content만 흉내 낸다."""

    def __init__(self, content):
        self.content = content
        self.urls = []

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        return self

    def raise_for_status(self):
        pass

    def close(self):
        self.closed = True


def rss_xml(items):
    published = format_datetime(datetime.now(timezone.utc) - timedelta(days=1))
    body = "".join(
        f"<item><title>{title} - {source}</title>"
        f"<link>https://news.google.com/rss/articles/ART{index}?oc=5</link>"
        f"<pubDate>{published}</pubDate><source url='https://example.com'>{source}</source></item>"
        for index, (title, source) in enumerate(items)
    )
    return f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>{body}</channel></rss>".encode()


def real_categories():
    categories, _collect = handler.load_crawler()
    return categories


def fake_collect(failing=(), per_query=1, empty=False):
    """검색어마다 기사 per_query건(한글 제목). failing에 든 검색어는 연결 오류."""
    calls = []

    def collect(query, title_keywords, days, session=None):
        calls.append(query)
        if query in failing:
            raise ConnectionError(f"{query} 연결 실패")
        if empty:
            return []
        return [
            {
                "title": f"생성형 AI 산업 동향 {index} ({query})",
                "source": "테스트신문",
                "link": f"https://news.google.com/rss/articles/{abs(hash(query))}-{index}?oc=5",
                "published": "2026-11-16T00:00:00+00:00",
            }
            for index in range(per_query)
        ]

    collect.calls = calls
    return collect


SETTINGS = handler.Settings(bucket="playmate-test-bucket", prefix="raw/news/", days=7, pause_seconds=0)
FIXED_NOW = datetime(2026, 11, 17, 9, 0, 5, tzinfo=timezone.utc)
SCHEDULED_EVENT = {"scheduled_time": "2026-11-17T09:00:00Z"}


def run(event=None, collect=None, s3=None, context=None, session=None, **kwargs):
    s3 = s3 or FakeS3()
    collector = None if collect is None else (real_categories(), collect)
    result = handler.run_collection(
        SCHEDULED_EVENT if event is None else event,
        context or NoTimeLimitContext(),
        settings=kwargs.pop("settings", SETTINGS),
        s3_client=s3,
        collector=collector,
        session=session,
        now=lambda: FIXED_NOW,
        **kwargs,
    )
    return result, s3


def uploaded_document(s3):
    (body,) = s3.objects.values()
    return json.loads(body.decode("utf-8"))


class NetworkGuardMixin:
    def setUp(self):
        _NETWORK_ATTEMPTS.clear()

    def tearDown(self):
        self.assertEqual(_NETWORK_ATTEMPTS, [], "테스트 중 외부 네트워크 접속 시도가 있었습니다")


# -- 기존 코드 재사용 ------------------------------------------------------------------
class ReuseTests(NetworkGuardMixin, unittest.TestCase):
    def test_uses_existing_eight_categories_from_crawler_config(self):
        module = handler._collect_module()
        categories, collect = handler.load_crawler()
        self.assertEqual({name: spec["code"] for name, spec in categories.items()}, module.FIELD_CODES)
        self.assertEqual(len(categories), 8)
        crawler_dir = (REPO_ROOT / "crawler" / "career_news_crawler").resolve()
        self.assertTrue(Path(sys.modules["config"].__file__).resolve().is_relative_to(crawler_dir))
        self.assertEqual(collect.__name__, "collect_google_news")
        self.assertTrue(Path(module.__file__).resolve().samefile(
            REPO_ROOT / "database" / "scripts" / "collect_career_news.py"))

    def test_every_query_of_every_category_is_recorded(self):
        collect = fake_collect()
        result, s3 = run(collect=collect)
        doc = uploaded_document(s3)
        expected = [query for spec in real_categories().values() for query in spec["queries"]]
        self.assertEqual(collect.calls, expected)
        self.assertEqual([q["query"] for c in doc["categories"] for q in c["queries"]], expected)
        self.assertEqual([c["code"] for c in doc["categories"]],
                         [spec["code"] for spec in real_categories().values()])
        self.assertEqual(result["summary"]["query_count"], len(expected))

    def test_real_collector_with_fixed_rss_response(self):
        """실제 collect_google_news(제목 필터·제외 출처·언론사 분리)를 고정 RSS로 실행한다."""
        session = FakeRssSession(rss_xml([
            ("생성형 AI 기술 투자 확대", "테스트신문"),
            ("자바스크립트 룰렛 화면 구성", "Calgary Roughnecks"),
            ("반도체 가격 상승", "경제신문"),
        ]))
        result, s3 = run(session=session)
        doc = uploaded_document(s3)
        data_ai = next(c for c in doc["categories"] if c["code"] == "data_ai")
        article = data_ai["queries"][0]["articles"][0]
        self.assertEqual(set(article), set(handler.ARTICLE_FIELDS))
        self.assertEqual(article["title"], "생성형 AI 기술 투자 확대")
        self.assertEqual(article["source"], "테스트신문")
        # raw는 크롤러 결과 그대로: 링크 정규화(oc 제거)는 하지 않는다.
        self.assertEqual(article["link"], "https://news.google.com/rss/articles/ART0?oc=5")
        titles = {a["title"] for c in doc["categories"] for q in c["queries"] for a in q["articles"]}
        self.assertNotIn("반도체 가격 상승", titles)
        self.assertNotIn("자바스크립트 룰렛 화면 구성", titles)
        self.assertEqual(len(session.urls), result["summary"]["query_count"])
        self.assertIn("news.google.com/rss/search", session.urls[0])


# -- raw JSON ------------------------------------------------------------------------
class RawDocumentTests(NetworkGuardMixin, unittest.TestCase):
    def test_top_level_fields_and_article_fields(self):
        _, s3 = run(collect=fake_collect(per_query=2))
        doc = uploaded_document(s3)
        self.assertEqual(list(doc), ["schema_version", "run_id", "collected_at", "categories",
                                     "collection_summary"])
        self.assertEqual(doc["schema_version"], handler.SCHEMA_VERSION)
        self.assertEqual(doc["run_id"], "20261117T090000Z-scheduled")
        self.assertEqual(doc["collected_at"], "2026-11-17T09:00:05Z")
        self.assertEqual(doc["collection_summary"]["data_kind"], "filtered_rss_results")
        query = doc["categories"][0]["queries"][0]
        self.assertEqual(query["status"], "ok")
        self.assertIsNone(query["error"])
        self.assertEqual(query["article_count"], 2)
        self.assertEqual(set(query["articles"][0]), {"title", "source", "link", "published"})

    def test_korean_title_is_stored_as_utf8_text(self):
        _, s3 = run(collect=fake_collect())
        body = next(iter(s3.objects.values()))
        text = body.decode("utf-8")
        self.assertIn("생성형 AI 산업 동향", text)
        self.assertNotIn("\\uc0dd", text)  # '생'의 유니코드 이스케이프가 없어야 한다
        self.assertIn("데이터·AI", text)

    def test_no_body_or_original_url_fields_are_invented(self):
        _, s3 = run(collect=fake_collect())
        text = next(iter(s3.objects.values())).decode("utf-8")
        for invented in ('"body"', '"content"', '"original_url"', '"description"'):
            self.assertNotIn(invented, text)


# -- 성공·부분 실패·전체 실패·0건 ----------------------------------------------------------
class StatusTests(NetworkGuardMixin, unittest.TestCase):
    def test_all_success_is_ok(self):
        result, s3 = run(collect=fake_collect())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"]["failed_queries"], 0)
        self.assertEqual(len(s3.calls), 1)

    def test_partial_failure_keeps_query_level_errors(self):
        categories = real_categories()
        data_ai_queries = categories["데이터·AI"]["queries"]
        backend_first = categories["백엔드·서버"]["queries"][0]
        failing = set(data_ai_queries) | {backend_first}
        result, s3 = run(collect=fake_collect(failing=failing))
        doc = uploaded_document(s3)
        by_code = {c["code"]: c for c in doc["categories"]}
        self.assertEqual(result["status"], "partial")
        self.assertEqual(by_code["data_ai"]["status"], "failed")
        self.assertEqual(by_code["backend"]["status"], "partial")
        self.assertEqual(by_code["frontend"]["status"], "ok")
        self.assertEqual(doc["collection_summary"]["failed_categories"], ["data_ai"])
        self.assertEqual(doc["collection_summary"]["partial_categories"], ["backend"])
        failed_query = by_code["backend"]["queries"][0]
        self.assertEqual(failed_query["status"], "failed")
        self.assertEqual(failed_query["error"]["type"], "ConnectionError")
        self.assertIn("연결 실패", failed_query["error"]["message"])
        self.assertEqual(failed_query["articles"], [])
        self.assertEqual(doc["collection_summary"]["failed_queries"], len(failing))

    def test_total_failure_raises_and_does_not_upload(self):
        everything = {q for spec in real_categories().values() for q in spec["queries"]}
        s3 = FakeS3()
        with self.assertRaises(handler.CollectionFailedError) as caught:
            run(collect=fake_collect(failing=everything), s3=s3)
        self.assertEqual(s3.calls, [])
        self.assertEqual(caught.exception.summary["status"], "failed")
        self.assertEqual(caught.exception.summary["succeeded_queries"], 0)
        self.assertEqual(sorted(caught.exception.summary["failed_categories"]),
                         sorted(spec["code"] for spec in real_categories().values()))

    def test_zero_articles_is_empty_and_still_uploaded(self):
        result, s3 = run(collect=fake_collect(empty=True))
        self.assertEqual(result["status"], "empty")
        doc = uploaded_document(s3)
        self.assertEqual(doc["collection_summary"]["article_count"], 0)
        self.assertEqual(doc["collection_summary"]["failed_queries"], 0)
        self.assertTrue(all(q["status"] == "ok" for c in doc["categories"] for q in c["queries"]))

    def test_time_budget_skips_requests_instead_of_running_out(self):
        """남은 시간이 부족하면 요청하지 않고 TimeBudgetExceeded로 기록, 업로드 시간은 남긴다."""
        ticks = iter(range(0, 10_000, 30))  # 호출마다 30초씩 흐르는 가짜 시계
        collect = fake_collect()
        context = FakeContext(remaining_ms=150_000)  # 150초 - 업로드 예비 20초 = 130초 사용 가능
        result, s3 = run(collect=collect, context=context, clock=lambda: next(ticks))
        doc = uploaded_document(s3)
        skipped = [q for c in doc["categories"] for q in c["queries"]
                   if q["error"] and q["error"]["type"] == "TimeBudgetExceeded"]
        self.assertTrue(skipped)
        self.assertLess(len(collect.calls), result["summary"]["query_count"])
        self.assertEqual(result["status"], "partial")

    def test_no_time_at_all_is_total_failure(self):
        context = FakeContext(remaining_ms=1_000)
        collect = fake_collect()
        s3 = FakeS3()
        with self.assertRaises(handler.CollectionFailedError):
            run(collect=collect, context=context, s3=s3, clock=lambda: 0.0)
        self.assertEqual(collect.calls, [])
        self.assertEqual(s3.calls, [])


# -- S3 키·업로드 ----------------------------------------------------------------------
class S3Tests(NetworkGuardMixin, unittest.TestCase):
    def test_object_key_and_put_object_arguments(self):
        result, s3 = run(collect=fake_collect())
        self.assertEqual(result["key"], "raw/news/2026/11/17/20261117T090000Z-scheduled.json")
        (call,) = s3.calls
        self.assertEqual(call["Bucket"], "playmate-test-bucket")
        self.assertEqual(call["Key"], result["key"])
        self.assertEqual(call["ContentType"], "application/json; charset=utf-8")
        self.assertEqual(call["IfNoneMatch"], "*")  # 조건부 쓰기: 이미 있으면 덮어쓰지 않음
        self.assertIsInstance(call["Body"], bytes)
        self.assertEqual(json.loads(call["Body"].decode("utf-8"))["run_id"], result["run_id"])
        self.assertEqual(result["outcome"], "created")

    def test_run_id_sources(self):
        now = FIXED_NOW
        self.assertEqual(handler.resolve_run_id({"run_id": "20261117T090000Z-manual"}, None, now),
                         "20261117T090000Z-manual")
        self.assertEqual(handler.resolve_run_id({"time": "2026-11-17T18:30:00+09:00"}, None, now),
                         "20261117T093000Z-scheduled")
        self.assertEqual(handler.resolve_run_id({}, FakeContext("abc-123"), now),
                         "20261117T090005Z-abc-123")
        generated = handler.resolve_run_id({}, None, now)
        self.assertRegex(generated, handler.RUN_ID_PATTERN)

    def test_same_run_id_retry_keeps_first_raw(self):
        """같은 run_id 재시도: 같은 키에 조건부 쓰기 → 412 → 기존 raw 확인 → 처음 raw 보존(정상 중복 실행)."""
        s3 = FakeS3()
        first, _ = run(collect=fake_collect(), s3=s3)
        original = s3.objects[first["key"]]
        with self.assertLogs(handler.logger, level="INFO") as logs:
            second, _ = run(collect=fake_collect(per_query=2), s3=s3)
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(len(s3.objects), 1)
        self.assertEqual(s3.objects[first["key"]], original)  # 바이트까지 그대로
        self.assertEqual(second["outcome"], "already_exists")
        self.assertEqual(second["summary"], first["summary"])  # 이번 수집이 아니라 보존된 raw의 요약
        self.assertTrue(any("보존" in line for line in logs.output))


# -- 조건부 쓰기 실패 구분 -----------------------------------------------------------------------
class ConditionalWriteTests(NetworkGuardMixin, unittest.TestCase):
    KEY = "raw/news/2026/11/17/20261117T090000Z-scheduled.json"

    def test_existing_object_of_another_run_is_conflict_and_untouched(self):
        s3 = FakeS3()
        foreign = json.dumps({"schema_version": handler.SCHEMA_VERSION, "run_id": "20261117T090000Z-other",
                              "collection_summary": {"status": "ok"}}).encode()
        for body in (foreign, b"not json", b"[1, 2]",
                     json.dumps({"schema_version": handler.SCHEMA_VERSION,
                                 "run_id": "20261117T090000Z-scheduled",
                                 "collection_summary": {"status": "failed"}}).encode()):
            with self.subTest(body=body[:30]):
                s3.objects[self.KEY] = body
                with self.assertRaises(handler.RawConflictError):
                    run(collect=fake_collect(), s3=s3)
                self.assertEqual(s3.objects[self.KEY], body)  # 삭제·덮어쓰기 없음

    def test_cannot_read_existing_object_is_upload_error_not_duplicate(self):
        s3 = FakeS3()
        run(collect=fake_collect(), s3=s3)
        s3.get_error = TimeoutError("read timeout")
        with self.assertRaises(handler.RawUploadError) as caught:
            run(collect=fake_collect(), s3=s3)
        self.assertNotIsInstance(caught.exception, handler.RawConflictError)

    def test_409_conflict_is_retryable_error(self):
        s3 = FakeS3(error=FakeClientError("ConditionalRequestConflict", 409))
        with self.assertRaises(handler.RawWriteConflictError) as caught:
            run(collect=fake_collect(), s3=s3)
        self.assertIsInstance(caught.exception, handler.RawUploadError)
        self.assertIn("재시도", str(caught.exception))
        self.assertEqual(s3.objects, {})

    def test_other_client_errors_and_old_sdk_are_upload_errors(self):
        for error in (FakeClientError("AccessDenied", 403), FakeClientError("InternalError", 500),
                      TypeError("Unknown parameter in input: IfNoneMatch")):
            with self.subTest(error=error):
                s3 = FakeS3(error=error)
                with self.assertRaises(handler.RawUploadError) as caught:
                    run(collect=fake_collect(), s3=s3)
                self.assertNotIsInstance(caught.exception, (handler.RawConflictError,
                                                            handler.RawWriteConflictError))
                self.assertEqual(s3.gets, [])

    def test_key_date_comes_from_run_id_not_retry_time(self):
        key = handler.build_object_key("raw/news/", "20261231T235959Z-scheduled")
        self.assertEqual(key, "raw/news/2026/12/31/20261231T235959Z-scheduled.json")

    def test_invalid_run_id_and_schedule_time_are_rejected_before_collecting(self):
        collect = fake_collect()
        for event in ({"run_id": "../../processed/x"}, {"run_id": 123}, {"time": "2026-11-17T09:00:00"}):
            with self.subTest(event=event), self.assertRaises(handler.ConfigError):
                run(event=event, collect=collect)
        self.assertEqual(collect.calls, [])

    def test_upload_exception_is_not_reported_as_success(self):
        s3 = FakeS3(error=TimeoutError("network down"))
        with self.assertRaises(handler.RawUploadError) as caught:
            run(collect=fake_collect(), s3=s3)
        self.assertIsInstance(caught.exception.__cause__, TimeoutError)
        self.assertIn("raw/news/2026/11/17/", str(caught.exception))

    def test_upload_without_http_200_is_failure(self):
        with self.assertRaises(handler.RawUploadError):
            run(collect=fake_collect(), s3=FakeS3(status=500))


# -- 검수 보완: 실패 기록·상태 경계 ------------------------------------------------------
class FailureReportingTests(NetworkGuardMixin, unittest.TestCase):
    def test_total_failure_message_carries_run_id_and_error_types(self):
        """Lambda 실패 기록에는 예외 메시지만 남으므로 재시도·알림에 필요한 정보가 메시지에 있어야 한다."""
        everything = {q for spec in real_categories().values() for q in spec["queries"]}
        with self.assertLogs(handler.logger, level="ERROR") as logs, \
                self.assertRaises(handler.CollectionFailedError) as caught:
            run(collect=fake_collect(failing=everything))
        message = str(caught.exception)
        self.assertIn("run_id=20261117T090000Z-scheduled", message)
        self.assertIn(f"'ConnectionError': {len(everything)}", message)
        self.assertTrue(any("run_id=20261117T090000Z-scheduled" in line for line in logs.output))

    def test_partial_failure_is_logged_as_warning(self):
        failing = {real_categories()["정보보안"]["queries"][0]}
        with self.assertLogs(handler.logger, level="WARNING") as logs:
            result, _ = run(collect=fake_collect(failing=failing))
        self.assertEqual(result["status"], "partial")
        warning = "\n".join(line for line in logs.output if line.startswith("WARNING"))
        self.assertIn("security", warning)
        self.assertIn("'ConnectionError': 1", warning)

    def test_partial_failure_with_zero_articles_stays_partial_not_empty(self):
        failing = {real_categories()["정보보안"]["queries"][0]}
        result, s3 = run(collect=fake_collect(failing=failing, empty=True))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["summary"]["article_count"], 0)
        self.assertEqual(len(s3.calls), 1)

    def test_non_mapping_event_uses_request_id(self):
        from types import SimpleNamespace

        result, _ = run(event="not-a-dict", collect=fake_collect(),
                        context=SimpleNamespace(aws_request_id="req-123"))
        self.assertEqual(result["run_id"], "20261117T090005Z-req-123")


# -- 검수 보완: Lambda 배포 묶음 구조 -----------------------------------------------------
class BundleLayoutTests(NetworkGuardMixin, unittest.TestCase):
    """README의 배포 묶음처럼 한 폴더에 파일을 모았을 때 저장소 경로 없이 동작하는지 확인한다."""

    SHARED = ("config", "src", "src.rss_collector", "import_career_news", "collect_career_news")

    def test_handler_runs_from_flat_bundle_without_repo_paths(self):
        import shutil
        import tempfile

        saved_modules = {name: sys.modules.pop(name) for name in self.SHARED if name in sys.modules}
        saved_path = list(sys.path)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "task"
            (bundle / "src").mkdir(parents=True)
            crawler = REPO_ROOT / "crawler" / "career_news_crawler"
            scripts = REPO_ROOT / "database" / "scripts"
            shutil.copy(HANDLER_PATH, bundle / "collector_handler.py")
            shutil.copy(scripts / "collect_career_news.py", bundle)
            shutil.copy(scripts / "import_career_news.py", bundle)
            shutil.copy(crawler / "config.py", bundle)
            shutil.copy(crawler / "src" / "__init__.py", bundle / "src")
            shutil.copy(crawler / "src" / "rss_collector.py", bundle / "src")
            try:
                spec = importlib.util.spec_from_file_location("bundle_collector_handler",
                                                              bundle / "collector_handler.py")
                bundled = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = bundled
                spec.loader.exec_module(bundled)
                with mock.patch.dict("os.environ", {}, clear=False) as environ:
                    environ.pop("NEWS_CRAWLER_DIR", None)
                    session = FakeRssSession(rss_xml([("생성형 AI 기술 투자 확대", "테스트신문")]))
                    s3 = FakeS3()
                    result = bundled.run_collection(SCHEDULED_EVENT, NoTimeLimitContext(), settings=SETTINGS,
                                                    s3_client=s3, session=session, now=lambda: FIXED_NOW)
                bundle_root = bundle.resolve()
                for name in ("config", "src.rss_collector", "import_career_news"):
                    self.assertTrue(Path(sys.modules[name].__file__).resolve().is_relative_to(bundle_root), name)
                self.assertTrue(Path(bundled._collect_module().__file__).resolve().is_relative_to(bundle_root))
                self.assertEqual(result["key"], "raw/news/2026/11/17/20261117T090000Z-scheduled.json")
                self.assertGreater(result["summary"]["article_count"], 0)
            finally:
                for name in self.SHARED:
                    sys.modules.pop(name, None)
                sys.modules.pop("bundle_collector_handler", None)
                sys.modules.update(saved_modules)
                sys.path[:] = saved_path


# -- 설정·진입점·로그 ---------------------------------------------------------------------
class SettingsAndHandlerTests(NetworkGuardMixin, unittest.TestCase):
    def test_settings_from_env(self):
        settings = handler.Settings.from_env({"NEWS_RAW_BUCKET": "playmate-news",
                                              "NEWS_DAYS": "3", "NEWS_PAUSE_SECONDS": "0.5"})
        self.assertEqual((settings.bucket, settings.prefix, settings.days, settings.pause_seconds),
                         ("playmate-news", "raw/news/", 3, 0.5))

    def test_settings_reject_missing_bucket_bad_values_and_non_raw_prefix(self):
        bad = [
            {},
            {"NEWS_RAW_BUCKET": "Bad_Bucket"},
            {"NEWS_RAW_BUCKET": "playmate-news", "NEWS_DAYS": "31"},
            {"NEWS_RAW_BUCKET": "playmate-news", "NEWS_DAYS": "x"},
            {"NEWS_RAW_BUCKET": "playmate-news", "NEWS_RAW_PREFIX": "processed/news/"},
            {"NEWS_RAW_BUCKET": "playmate-news", "NEWS_RAW_PREFIX": "raw/../processed/"},
        ]
        for environ in bad:
            with self.subTest(environ=environ), self.assertRaises(handler.ConfigError):
                handler.Settings.from_env(environ)

    def test_lambda_handler_wiring_without_aws(self):
        s3 = FakeS3()
        session = FakeRssSession(rss_xml([("생성형 AI 기술 투자 확대", "테스트신문")]))
        environ = {"NEWS_RAW_BUCKET": "playmate-news", "NEWS_PAUSE_SECONDS": "0",
                   "AWS_SECRET_ACCESS_KEY": "do-not-log-this-secret"}
        with mock.patch.dict("os.environ", environ, clear=False), \
                mock.patch.object(handler, "_new_s3_client", return_value=s3), \
                mock.patch.object(handler, "_new_session", return_value=session), \
                mock.patch.object(handler, "_S3_CLIENT", None), \
                self.assertLogs(handler.logger, level="INFO") as logs:
            result = handler.lambda_handler({"scheduled_time": "2026-11-17T09:00:00Z"}, NoTimeLimitContext())
        self.assertEqual(result["bucket"], "playmate-news")
        self.assertEqual(result["key"], "raw/news/2026/11/17/20261117T090000Z-scheduled.json")
        self.assertNotIn("categories", result)  # 응답에는 기사 목록을 넣지 않는다
        joined = "\n".join(logs.output)
        self.assertNotIn("do-not-log-this-secret", joined)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", joined)
        self.assertNotIn("boto3", sys.modules)

    def test_runtime_without_if_none_match_stops_before_collecting(self):
        """런타임 boto3가 IfNoneMatch를 모르면 RSS 요청 전에 멈추고 클라이언트를 캐시하지 않는다."""
        from types import SimpleNamespace

        def client_with(members):
            model = SimpleNamespace(operation_model=lambda name: SimpleNamespace(
                input_shape=SimpleNamespace(members=dict.fromkeys(members))))
            s3 = FakeS3()
            s3.meta = SimpleNamespace(service_model=model)
            return s3

        old = client_with(["Bucket", "Key", "Body", "ContentType"])
        with mock.patch.dict("os.environ", {"NEWS_RAW_BUCKET": "playmate-news"}, clear=False), \
                mock.patch.object(handler, "_new_s3_client", return_value=old), \
                mock.patch.object(handler, "_new_session") as new_session, \
                mock.patch.object(handler, "_S3_CLIENT", None):
            with self.assertRaises(handler.ConfigError) as caught:
                handler.lambda_handler(SCHEDULED_EVENT, NoTimeLimitContext())
            self.assertIsNone(handler._S3_CLIENT)
        self.assertIn("IfNoneMatch", str(caught.exception))
        new_session.assert_not_called()
        self.assertEqual(old.calls, [])
        handler.ensure_conditional_write_supported(client_with(["Bucket", "Key", "IfNoneMatch"]))  # 통과

    def test_lambda_handler_missing_bucket_fails_before_network(self):
        with mock.patch.dict("os.environ", {"NEWS_RAW_BUCKET": ""}, clear=False), \
                mock.patch.object(handler, "_new_session") as new_session:
            with self.assertRaises(handler.ConfigError):
                handler.lambda_handler({}, NoTimeLimitContext())
        new_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
