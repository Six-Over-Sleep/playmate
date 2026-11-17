"""Processor Lambda(processor_handler.py) 단위 테스트 — 인터넷·AWS·DB 없이 실행한다.

실행(저장소 루트): python -m unittest discover -s crawler/news_lambda/tests -v

- raw 입력은 직접 만들지 않고 실제 Collector(run_collection)가 만든 JSON을 쓴다(두 Lambda 사이의 규격 확인).
- S3는 get_object/head_object/put_object만 흉내 내는 가짜 클라이언트를 쓴다(boto3를 불러오지 않음).
- socket 연결·주소 조회를 막고 매 테스트 끝에 접속 시도가 없었는지 확인한다.
"""

import copy
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
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
    for name in set(sys.modules) - _SAVED_MODULES:
        del sys.modules[name]
    sys.path[:] = _SAVED_PATH


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


processor = _load("processor_handler_under_test", HERE / "processor_handler.py")
C = processor.collector          # raw 규격을 만드는 실제 Collector 모듈
I = processor.importer           # database/scripts/import_career_news.py

RAW_BUCKET = "playmate-raw-bucket"
FIXED_NOW = datetime(2026, 11, 17, 9, 0, 5, tzinfo=timezone.utc)
SETTINGS = processor.ProcessorSettings()


# -- 가짜 S3 --------------------------------------------------------------------------
class FakeS3:
    def __init__(self):
        self.objects = {}           # (bucket, key) -> {"body", "etag", "version"}
        self.gets, self.heads, self.puts = [], [], []
        self.get_error = None
        self.head_error = None
        self.put_error = None
        self.put_status = 200
        self.on_head = None         # head 직전 실행할 동작(처리 중 재업로드 흉내)
        self._version = 0

    def store(self, bucket, key, body):
        self._version += 1
        self.objects[(bucket, key)] = {"body": body, "etag": '"%s"' % hashlib.md5(body).hexdigest(),
                                       "version": f"v{self._version}"}
        return self.objects[(bucket, key)]

    def get_object(self, **kwargs):
        self.gets.append(kwargs)
        if self.get_error is not None:
            raise self.get_error
        obj = self.objects.get((kwargs["Bucket"], kwargs["Key"]))
        if obj is None:
            raise KeyError("NoSuchKey")
        return {"Body": io.BytesIO(obj["body"]), "ETag": obj["etag"], "VersionId": obj["version"],
                "ContentLength": len(obj["body"])}

    def head_object(self, **kwargs):
        self.heads.append(kwargs)
        if self.on_head is not None:
            action, self.on_head = self.on_head, None
            action()
        if self.head_error is not None:
            raise self.head_error
        obj = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"ETag": obj["etag"], "VersionId": obj["version"]}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        if self.put_error is not None:
            raise self.put_error
        self.store(kwargs["Bucket"], kwargs["Key"], kwargs["Body"])
        return {"ResponseMetadata": {"HTTPStatusCode": self.put_status}}


class _CollectorS3:
    def put_object(self, **kwargs):
        self.kwargs = kwargs
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}


# -- raw 만들기(실제 Collector 사용) ---------------------------------------------------------
def categories():
    return C.load_crawler()[0]


def query_of(name, index=0):
    return categories()[name]["queries"][index]


def collect_from(table, failing=()):
    """table: {검색어: [기사 dict, ...]}. 없는 검색어는 0건, failing은 연결 오류."""
    def collect(query, title_keywords, days, session=None):
        if query in failing:
            raise ConnectionError(f"{query} 연결 실패")
        return [dict(article) for article in table.get(query, [])]
    return collect


def make_raw(table=None, failing=(), event=None):
    """실제 Collector로 raw 키와 본문(bytes)을 만든다."""
    s3 = _CollectorS3()
    result = C.run_collection(
        event or {"scheduled_time": "2026-11-17T09:00:00Z"}, None,
        settings=C.Settings(bucket=RAW_BUCKET, pause_seconds=0), s3_client=s3,
        collector=(categories(), collect_from(table or {}, failing)), now=lambda: FIXED_NOW,
    )
    return result["key"], s3.kwargs["Body"]


def article(title, link, published="2026-11-16T23:10:00+00:00", source="테스트신문"):
    return {"title": title, "source": source, "link": link, "published": published}


def s3_event(*keys, bucket=RAW_BUCKET, name="ObjectCreated:Put", version=None):
    return {"Records": [
        {"eventSource": "aws:s3", "eventName": name,
         "s3": {"bucket": {"name": bucket}, "object": {"key": key, "versionId": version, "sequencer": "0A"}}}
        for key in keys
    ]}


def run(s3, *keys, **kwargs):
    return processor.process_event(s3_event(*keys, **kwargs), settings=SETTINGS, s3_client=s3)


def stored_raw(table=None, failing=(), event=None):
    s3 = FakeS3()
    key, body = make_raw(table, failing, event)
    s3.store(RAW_BUCKET, key, body)
    return s3, key


def processed_doc(s3, raw_key):
    processed_key = raw_key.replace("raw/news/", "processed/news/", 1)
    return json.loads(s3.objects[(RAW_BUCKET, processed_key)]["body"].decode("utf-8"))


class NetworkGuardMixin:
    def setUp(self):
        _NETWORK_ATTEMPTS.clear()

    def tearDown(self):
        self.assertEqual(_NETWORK_ATTEMPTS, [], "테스트 중 외부 네트워크 접속 시도가 있었습니다")


# -- 정상 처리·정규화·중복 제거 ----------------------------------------------------------------
class NormalizationTests(NetworkGuardMixin, unittest.TestCase):
    def test_normal_raw_is_normalized_with_existing_functions(self):
        link = "HTTPS://News.Google.com/rss/articles/ABC?oc=5&utm_source=x#frag"
        s3, key = stored_raw({query_of("데이터·AI"): [
            article("  생성형   AI\n기술 투자 확대 ", link, published="2026-11-17T08:10:00+09:00"),
        ]})
        result = run(s3, key)
        (record,) = result["results"]
        self.assertEqual(record["status"], "written")
        self.assertEqual(record["processed_key"], "processed/news/2026/11/17/20261117T090000Z-scheduled.json")
        (out,) = processed_doc(s3, key)["articles"]
        normalized = "https://news.google.com/rss/articles/ABC"
        self.assertEqual(out, {
            "link_key": I.link_key_of(normalized),
            "link_url": normalized,
            "link_type": "GOOGLE_NEWS_RSS",
            "title": "생성형 AI 기술 투자 확대",
            "source_name": "테스트신문",
            "published_at": "2026-11-16T23:10:00Z",
            "field_codes": ["data_ai"],
        })
        self.assertEqual(I.normalize_link(link), normalized)

    def test_same_url_is_merged_and_field_codes_combined(self):
        shared = "https://news.google.com/rss/articles/SHARED?oc=5"
        variant = "https://news.google.com/rss/articles/SHARED?utm_medium=rss"
        s3, key = stored_raw({
            query_of("데이터·AI", 0): [article("AI 보안 위협 증가", shared)],
            query_of("데이터·AI", 1): [article("AI 보안 위협 증가", variant)],
            query_of("정보보안", 0): [article("AI 보안 위협 증가 (다른 제목)", shared)],
        })
        run(s3, key)
        doc = processed_doc(s3, key)
        (out,) = doc["articles"]
        self.assertEqual(out["field_codes"], ["data_ai", "security"])
        self.assertEqual(out["title"], "AI 보안 위협 증가")  # 처음 나온 기사 값을 유지(build_articles 규칙)
        self.assertEqual(doc["processing"]["input_rows"], 3)
        self.assertEqual(doc["processing"]["article_count"], 1)
        self.assertEqual(doc["processing"]["multi_field_article_count"], 1)

    def test_invalid_rows_are_counted_not_invented(self):
        s3, key = stored_raw({query_of("데이터·AI"): [
            article("링크가 잘못된 기사", "ftp://example.com/a"),
            article("   ", "https://example.com/b"),
            article("정상 기사", "https://Example.com/c?utm_campaign=z", published=None, source=""),
            article("RFC822 날짜", "https://example.com/d", published="Mon, 16 Nov 2026 23:10:00 GMT"),
        ]})
        run(s3, key)
        doc = processed_doc(s3, key)
        self.assertEqual(doc["processing"]["skipped"], {"empty_title": 1, "invalid_link": 1})
        by_title = {a["title"]: a for a in doc["articles"]}
        self.assertIsNone(by_title["정상 기사"]["published_at"])
        self.assertEqual(by_title["정상 기사"]["link_url"], "https://example.com/c")
        self.assertEqual(by_title["정상 기사"]["link_type"], "UNVERIFIED")
        self.assertEqual(by_title["RFC822 날짜"]["published_at"], "2026-11-16T23:10:00Z")
        for article_json in doc["articles"]:
            self.assertEqual(set(article_json), {"link_key", "link_url", "link_type", "title",
                                                 "source_name", "published_at", "field_codes"})

    def test_published_at_round_trips_to_existing_db_parser(self):
        """processed의 'Z' 표기를 기존 parse_published에 넣으면 DB 적재와 같은 UTC 시각이 된다."""
        s3, key = stored_raw({query_of("데이터·AI"): [
            article("시각 확인", "https://example.com/t", published="2026-11-17T08:10:00+09:00")]})
        run(s3, key)
        (out,) = processed_doc(s3, key)["articles"]
        self.assertEqual(I.parse_published(out["published_at"]),
                         I.parse_published("2026-11-17T08:10:00+09:00"))

    def test_korean_json_is_stored_as_utf8_text(self):
        s3, key = stored_raw({query_of("데이터·AI"): [article("생성형 AI 기술 투자 확대", "https://e.com/k")]})
        run(s3, key)
        body = s3.objects[(RAW_BUCKET, key.replace("raw/", "processed/", 1))]["body"]
        text = body.decode("utf-8")
        self.assertIn("생성형 AI 기술 투자 확대", text)
        self.assertIn("데이터·AI", text)
        self.assertNotIn("\\uc0dd", text)
        put = s3.puts[-1]
        self.assertEqual(put["ContentType"], "application/json; charset=utf-8")


# -- 상태: 정상·0건·부분 실패 ------------------------------------------------------------------
class StatusTests(NetworkGuardMixin, unittest.TestCase):
    def test_all_ok_with_articles(self):
        s3, key = stored_raw({query_of("데이터·AI"): [article("기사", "https://e.com/1")]})
        run(s3, key)
        doc = processed_doc(s3, key)
        self.assertEqual(doc["collection"]["summary"]["status"], "ok")
        self.assertEqual(doc["processing"]["status"], "ok")
        self.assertEqual(doc["collection"]["query_failures"], [])

    def test_all_ok_but_zero_articles_is_empty(self):
        s3, key = stored_raw({})
        result = run(s3, key)
        doc = processed_doc(s3, key)
        self.assertEqual(doc["collection"]["summary"]["status"], "empty")
        self.assertEqual(doc["processing"]["status"], "empty")
        self.assertEqual(doc["articles"], [])
        self.assertEqual(result["results"][0]["status"], "written")

    def test_partial_failure_with_articles_keeps_failure_details_from_raw(self):
        failing = {query_of("백엔드·서버", 0)}
        s3, key = stored_raw({query_of("데이터·AI"): [article("기사", "https://e.com/1")]}, failing=failing)
        raw = json.loads(s3.objects[(RAW_BUCKET, key)]["body"])
        run(s3, key)
        doc = processed_doc(s3, key)
        self.assertEqual(doc["processing"]["status"], "partial")
        self.assertEqual(doc["collection"]["summary"], raw["collection_summary"])  # 그대로 보존
        (failure,) = doc["collection"]["query_failures"]
        raw_query = raw["categories"][1]["queries"][0]
        self.assertEqual(failure, {"category_code": "backend", "query": raw_query["query"],
                                   "error": raw_query["error"]})
        backend = next(c for c in doc["collection"]["categories"] if c["code"] == "backend")
        self.assertEqual(backend["status"], "partial")
        self.assertEqual(doc["processing"]["article_count"], 1)

    def test_partial_failure_with_zero_articles_stays_partial(self):
        failing = set(categories()["정보보안"]["queries"])
        s3, key = stored_raw({}, failing=failing)
        run(s3, key)
        doc = processed_doc(s3, key)
        self.assertEqual(doc["processing"]["status"], "partial")
        self.assertEqual(doc["processing"]["article_count"], 0)
        self.assertEqual(doc["collection"]["summary"]["failed_categories"], ["security"])
        self.assertEqual(len(doc["collection"]["query_failures"]), len(failing))


# -- 잘못된 raw -----------------------------------------------------------------------------
class InvalidRawTests(NetworkGuardMixin, unittest.TestCase):
    def assert_rejected(self, s3, key, fragment):
        with self.assertRaises(processor.ProcessingError) as caught:
            run(s3, key)
        (result,) = caught.exception.results
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["type"], "RawValidationError")
        self.assertIn(fragment, result["error"]["message"])
        self.assertEqual(s3.puts, [])  # 잘못된 raw는 빈 결과로도 저장하지 않는다

    def mutated(self, change):
        s3, key = stored_raw({query_of("데이터·AI"): [article("기사", "https://e.com/1")]})
        doc = json.loads(s3.objects[(RAW_BUCKET, key)]["body"])
        change(doc)
        s3.store(RAW_BUCKET, key, json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        return s3, key

    def test_broken_json_and_non_utf8(self):
        for body in (b'{"schema_version": "0.1-draft", "categories": [', b"\xff\xfe\x00"):
            with self.subTest(body=body):
                s3, key = stored_raw({})
                s3.store(RAW_BUCKET, key, body)
                self.assert_rejected(s3, key, "raw JSON 형식 오류")

    def test_empty_object_is_not_an_empty_news_list(self):
        s3, key = self.mutated(lambda doc: doc.clear())
        self.assert_rejected(s3, key, "raw.schema_version 누락")

    def test_missing_article_field(self):
        s3, key = self.mutated(lambda doc: doc["categories"][0]["queries"][0]["articles"][0].pop("link"))
        self.assert_rejected(s3, key, "raw.categories[0].queries[0].articles[0].link 누락")

    def test_missing_category_and_summary_fields(self):
        cases = {
            "raw.categories[2].code 누락": lambda doc: doc["categories"][2].pop("code"),
            "raw.collection_summary 누락": lambda doc: doc.pop("collection_summary"),
            "raw.categories[0].queries[1].error 누락": lambda doc: doc["categories"][0]["queries"][1].pop("error"),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment=fragment):
                s3, key = self.mutated(change)
                self.assert_rejected(s3, key, fragment)

    def test_contract_violations(self):
        cases = {
            "지원하지 않는 raw 규격 버전": lambda doc: doc.update(schema_version="9.9"),
            "객체 키의 run_id와 다릅니다": lambda doc: doc.update(run_id="20261117T090000Z-other"),
            "처리할 수 없는 수집 상태: failed": lambda doc: doc["collection_summary"].update(status="failed"),
            "PlayMate 분야 코드가 아닙니다": lambda doc: doc["categories"][0].update(code="unknown"),
            "collection_summary.article_count": lambda doc: doc["collection_summary"].update(article_count=99),
            "article_count가 기사 수와 다릅니다":
                lambda doc: doc["categories"][0]["queries"][0].update(article_count=5),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment=fragment):
                s3, key = self.mutated(change)
                self.assert_rejected(s3, key, fragment)

    def test_unexpected_raw_key_name(self):
        s3 = FakeS3()
        for key in ("raw/news/2026/11/17/not-a-run-id.json",
                    "raw/news/2026/11/18/20261117T090000Z-scheduled.json"):
            with self.subTest(key=key):
                s3.store(RAW_BUCKET, key, b"{}")
                with self.assertRaises(processor.ProcessingError):
                    run(s3, key)
        self.assertEqual(s3.gets, [])  # 키가 규칙에 맞지 않으면 읽지도 않는다


# -- S3 이벤트·멱등성·순서 ----------------------------------------------------------------------
class EventTests(NetworkGuardMixin, unittest.TestCase):
    def test_s3_event_key_is_url_decoded(self):
        self.assertEqual(processor.decode_s3_key("raw/news/2026/11/17/a+b%3Dc.json"),
                         "raw/news/2026/11/17/a b=c.json")
        s3, key = stored_raw({})
        encoded = key.replace("/", "%2F").replace("-", "%2D")
        (record,) = run(s3, encoded)["results"]
        self.assertEqual(record["raw_key"], key)
        self.assertEqual(record["status"], "written")

    def test_multiple_records(self):
        s3, first = stored_raw({query_of("데이터·AI"): [article("첫째", "https://e.com/1")]})
        second, body = make_raw({query_of("정보보안"): [article("둘째", "https://e.com/2")]},
                                event={"run_id": "20261117T100000Z-manual"})
        s3.store(RAW_BUCKET, second, body)
        result = run(s3, first, second)
        self.assertEqual([r["status"] for r in result["results"]], ["written", "written"])
        self.assertEqual(processed_doc(s3, second)["articles"][0]["field_codes"], ["security"])

    def test_one_bad_record_does_not_block_good_one_but_fails_invocation(self):
        s3, good = stored_raw({query_of("데이터·AI"): [article("정상", "https://e.com/1")]})
        bad = "raw/news/2026/11/17/20261117T110000Z-manual.json"
        s3.store(RAW_BUCKET, bad, b"not json")
        with self.assertRaises(processor.ProcessingError) as caught:
            run(s3, bad, good)
        statuses = [r["status"] for r in caught.exception.results]
        self.assertEqual(statuses, ["failed", "written"])
        self.assertIn(bad, str(caught.exception))
        self.assertIn((RAW_BUCKET, good.replace("raw/", "processed/", 1)), s3.objects)

    def test_non_target_records_are_skipped_without_reading(self):
        s3 = FakeS3()
        event = s3_event("processed/news/2026/11/17/20261117T090000Z-scheduled.json",
                         "raw/news/2026/11/17/readme.txt", "other/x.json")
        event["Records"].append({"eventSource": "aws:s3", "eventName": "ObjectRemoved:Delete",
                                 "s3": {"bucket": {"name": RAW_BUCKET}, "object": {"key": "raw/news/x.json"}}})
        event["Records"].append({"eventSource": "aws:sqs"})
        result = processor.process_event(event, settings=SETTINGS, s3_client=s3)
        self.assertEqual([r.get("reason") for r in result["results"]],
                         ["outside_raw_prefix", "not_json", "outside_raw_prefix", "not_object_created",
                          "not_s3_event"])
        self.assertEqual(s3.gets, [])
        self.assertEqual(s3.puts, [])

    def test_invalid_event_shape(self):
        for event in ({}, {"Records": "x"}, None):
            with self.subTest(event=event), self.assertRaises(processor.InvalidEventError):
                processor.process_event(event, settings=SETTINGS, s3_client=FakeS3())

    def test_same_event_twice_gives_identical_output(self):
        s3, key = stored_raw({query_of("데이터·AI"): [article("같은 결과", "https://e.com/1")]})
        processed_key = key.replace("raw/", "processed/", 1)
        run(s3, key)
        first = s3.objects[(RAW_BUCKET, processed_key)]["body"]
        run(s3, key, key)  # 중복 전달(같은 이벤트 안에서 두 번 포함)도 같은 결과
        self.assertEqual(len(s3.puts), 3)
        self.assertTrue(all(put["Body"] == first for put in s3.puts))
        self.assertEqual([k for k in s3.objects if k[1].startswith("processed/")], [(RAW_BUCKET, processed_key)])

    def test_reads_latest_object_even_for_older_event_version(self):
        """이벤트 순서 역전: 오래된 버전(v1) 이벤트가 늦게 와도 최신 객체를 읽어 최신 결과를 쓴다."""
        s3, key = stored_raw({query_of("데이터·AI"): [article("첫 수집", "https://e.com/1")]})
        old_version = s3.objects[(RAW_BUCKET, key)]["version"]
        _, newer = make_raw({query_of("데이터·AI"): [article("재시도 수집", "https://e.com/2")]})
        s3.store(RAW_BUCKET, key, newer)  # Collector 재시도가 같은 키를 덮어씀
        (record,) = run(s3, key, version=old_version)["results"]
        self.assertNotIn("VersionId", s3.gets[0])  # 이벤트 버전이 아니라 최신 객체를 읽는다
        self.assertEqual(record["event_version_id"], old_version)
        self.assertNotEqual(record["raw_version_id"], old_version)
        self.assertEqual([a["title"] for a in processed_doc(s3, key)["articles"]], ["재시도 수집"])

    def test_reupload_during_processing_is_not_written(self):
        """읽은 뒤 같은 키가 다시 올라오면 오래된 결과로 덮어쓰지 않고, 새 업로드의 이벤트에 맡긴다."""
        s3, key = stored_raw({query_of("데이터·AI"): [article("오래된 내용", "https://e.com/1")]})
        _, newer = make_raw({query_of("데이터·AI"): [article("새 내용", "https://e.com/2")]})
        s3.on_head = lambda: s3.store(RAW_BUCKET, key, newer)
        (record,) = run(s3, key)["results"]
        self.assertEqual(record["status"], "superseded")
        self.assertEqual(s3.puts, [])


# -- S3 읽기·쓰기 실패 ---------------------------------------------------------------------------
class S3FailureTests(NetworkGuardMixin, unittest.TestCase):
    def failed_result(self, s3, key):
        with self.assertRaises(processor.ProcessingError) as caught:
            run(s3, key)
        (result,) = caught.exception.results
        return result

    def test_read_failure_and_missing_object(self):
        s3, key = stored_raw({})
        s3.get_error = TimeoutError("read timeout")
        self.assertEqual(self.failed_result(s3, key)["error"]["type"], "RawReadError")
        missing = FakeS3()
        self.assertEqual(self.failed_result(missing, key)["error"]["type"], "RawReadError")
        self.assertEqual(s3.puts + missing.puts, [])

    def test_head_failure_does_not_write(self):
        s3, key = stored_raw({})
        s3.head_error = TimeoutError("head timeout")
        self.assertEqual(self.failed_result(s3, key)["error"]["type"], "RawReadError")
        self.assertEqual(s3.puts, [])

    def test_write_failure_and_non_200(self):
        s3, key = stored_raw({})
        s3.put_error = TimeoutError("write timeout")
        self.assertEqual(self.failed_result(s3, key)["error"]["type"], "ProcessedWriteError")
        s3, key = stored_raw({})
        s3.put_status = 500
        self.assertEqual(self.failed_result(s3, key)["error"]["type"], "ProcessedWriteError")

    def test_oversized_raw_is_rejected(self):
        s3, key = stored_raw({})
        with mock.patch.object(processor, "MAX_RAW_BYTES", 10):
            self.assertEqual(self.failed_result(s3, key)["error"]["type"], "RawValidationError")


# -- 설정·진입점·배포 묶음 ---------------------------------------------------------------------
class SettingsAndHandlerTests(NetworkGuardMixin, unittest.TestCase):
    def test_settings(self):
        settings = processor.ProcessorSettings.from_env({})
        self.assertEqual((settings.raw_prefix, settings.processed_prefix, settings.processed_bucket),
                         ("raw/news/", "processed/news/", None))
        bad = [{"NEWS_PROCESSED_PREFIX": "raw/news/"}, {"NEWS_PROCESSED_PREFIX": "processed/../raw/"},
               {"NEWS_RAW_PREFIX": "processed/news/"}, {"NEWS_PROCESSED_BUCKET": "Bad_Bucket"}]
        for environ in bad:
            with self.subTest(environ=environ), self.assertRaises(processor.ConfigError):
                processor.ProcessorSettings.from_env(environ)

    def test_processed_bucket_override(self):
        s3, key = stored_raw({})
        settings = processor.ProcessorSettings(processed_bucket="playmate-processed")
        (record,) = processor.process_event(s3_event(key), settings=settings, s3_client=s3)["results"]
        self.assertEqual(record["processed_bucket"], "playmate-processed")
        self.assertIn(("playmate-processed", record["processed_key"]), s3.objects)

    def test_lambda_handler_without_aws(self):
        s3, key = stored_raw({query_of("데이터·AI"): [article("기사", "https://e.com/1")]})
        with mock.patch.dict("os.environ", {"AWS_SECRET_ACCESS_KEY": "do-not-log-this"}, clear=False), \
                mock.patch.object(processor, "_new_s3_client", return_value=s3), \
                mock.patch.object(processor, "_S3_CLIENT", None), \
                self.assertLogs(processor.logger, level="INFO") as logs:
            result = processor.lambda_handler(s3_event(key), None)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("do-not-log-this", "\n".join(logs.output))
        self.assertNotIn("boto3", sys.modules)

    def test_processor_runs_from_flat_bundle(self):
        names = ("collector_handler", "import_career_news")
        saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
        saved_path = list(sys.path)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "task"
            bundle.mkdir()
            for path in (HERE / "processor_handler.py", HERE / "collector_handler.py",
                         REPO_ROOT / "database" / "scripts" / "import_career_news.py"):
                shutil.copy(path, bundle)
            try:
                bundled = _load("bundle_processor_handler", bundle / "processor_handler.py")
                root = bundle.resolve()
                self.assertTrue(Path(bundled.collector.__file__).resolve().is_relative_to(root))
                self.assertTrue(Path(bundled.importer.__file__).resolve().is_relative_to(root))
                s3, key = stored_raw({query_of("데이터·AI"): [article("묶음", "https://e.com/1")]})
                result = bundled.process_event(s3_event(key), settings=bundled.ProcessorSettings(), s3_client=s3)
                self.assertEqual(result["results"][0]["status"], "written")
            finally:
                for name in names + ("bundle_processor_handler",):
                    sys.modules.pop(name, None)
                sys.modules.update(saved)
                sys.path[:] = saved_path


if __name__ == "__main__":
    unittest.main()
