"""Collector → S3 raw → ObjectCreated 이벤트 → Processor → S3 processed 로컬 통합 테스트.

실행(저장소 루트): python -m unittest discover -s crawler/news_lambda/tests -v

- 실제 8개 분야 설정과 실제 collect_google_news(제목 필터·언론사 분리·기간 필터)를 쓰고,
  RSS 응답만 검색어별 고정 XML을 돌려주는 가짜 session으로 바꾼다.
- 메모리 S3는 조건부 쓰기(IfNoneMatch="*" → 412, 409 흉내), ETag·버전, ObjectCreated 이벤트 생성을 흉내 낸다.
- 인터넷·AWS 접속을 막고 매 테스트 끝에 시도가 없었는지 확인한다.
"""

import hashlib
import importlib.util
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, quote_plus, urlsplit

HERE = Path(__file__).resolve().parents[1]

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


P = _load("processor_handler_integration", HERE / "processor_handler.py")
C = P.collector
BUCKET = "playmate-pipeline-test"
KST = timezone(timedelta(hours=9))
SCHEDULED = {"scheduled_time": "2026-11-17T09:00:00Z"}


# -- 메모리 S3 --------------------------------------------------------------------------
class ClientError(Exception):
    def __init__(self, code, status):
        super().__init__(code)
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


class InMemoryS3:
    def __init__(self):
        self.objects = {}
        self.pending_events = []
        self.gets = []
        self.conflict_once = False
        self._version = 0

    def put_object(self, Bucket, Key, Body, ContentType=None, IfNoneMatch=None):
        if self.conflict_once:
            self.conflict_once = False
            raise ClientError("ConditionalRequestConflict", 409)
        if IfNoneMatch == "*" and (Bucket, Key) in self.objects:
            raise ClientError("PreconditionFailed", 412)
        self._version += 1
        etag = '"%s"' % hashlib.md5(Body).hexdigest()
        self.objects[(Bucket, Key)] = {"body": Body, "etag": etag, "version": f"v{self._version}",
                                       "content_type": ContentType}
        # S3 이벤트 알림처럼 키를 URL 인코딩한다(공백은 '+').
        self.pending_events.append({
            "eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
            "s3": {"bucket": {"name": Bucket},
                   "object": {"key": quote_plus(Key, safe="/"), "versionId": f"v{self._version}",
                              "eTag": etag.strip('"'), "sequencer": f"{self._version:016X}"}},
        })
        return {"ResponseMetadata": {"HTTPStatusCode": 200}, "ETag": etag}

    def get_object(self, Bucket, Key, **kwargs):
        self.gets.append(Key)
        obj = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(obj["body"]), "ETag": obj["etag"], "VersionId": obj["version"],
                "ContentLength": len(obj["body"])}

    def head_object(self, Bucket, Key):
        obj = self.objects[(Bucket, Key)]
        return {"ETag": obj["etag"], "VersionId": obj["version"]}

    def take_events(self):
        events, self.pending_events = self.pending_events, []
        return {"Records": events}

    def body(self, key):
        return self.objects[(BUCKET, key)]["body"]


# -- 가짜 RSS ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class FakeRssSession:
    """검색어별 고정 RSS. collect_google_news가 만든 URL의 q에서 검색어를 꺼낸다."""

    def __init__(self, feeds, failing=()):
        self.feeds, self.failing, self.queries = feeds, set(failing), []

    def get(self, url, timeout=None, headers=None):
        query = parse_qs(urlsplit(url).query)["q"][0].rsplit(" when:", 1)[0]
        self.queries.append(query)
        if query in self.failing:
            raise ConnectionError(f"{query} 연결 실패")
        return FakeResponse(rss(self.feeds.get(query, [])))

    def close(self):
        pass


PUBLISHED = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0)


def rss(items):
    from xml.sax.saxutils import escape

    body = "".join(
        f"<item><title>{escape(title)} - {escape(source)}</title><link>{escape(link)}</link>"
        f"<pubDate>{format_datetime(PUBLISHED.astimezone(KST))}</pubDate>"
        f"<source url='https://example.com'>{source}</source></item>"
        for title, source, link in items
    )
    return f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>{body}</channel></rss>".encode()


CATEGORIES = C.load_crawler()[0]


def q(name, index=0):
    return CATEGORIES[name]["queries"][index]


G = "https://news.google.com/rss/articles/"
FEEDS = {
    q("데이터·AI", 0): [("AI 보안 위협 증가", "테스트신문", G + "SHARED?oc=5"),
                      ("생성형 AI 투자 확대", "테크신문", G + "GENAI?oc=5")],
    q("데이터·AI", 1): [("생성형 AI 투자 확대", "테크신문", G + "GENAI?oc=5&utm_source=rss")],
    q("정보보안", 0): [("AI 보안 위협 증가", "테스트신문", G + "SHARED?utm_medium=rss")],
    q("백엔드·서버", 0): [("백엔드 개발자 수요 변화", "개발신문", G + "BACKEND?oc=5")],
    q("프론트엔드·웹", 0): [("프론트엔드 성능 최적화 사례", "개발신문", G + "FRONT?oc=5")],
    q("모바일 개발", 0): [("안드로이드 앱 개발 도구 업데이트", "모바일신문", G + "MOBILE?oc=5")],
    q("클라우드·인프라", 0): [("클라우드 산업 성장 흐름", "인프라신문", G + "CLOUD?oc=5")],
    q("QA·테스트", 0): [("테스트 자동화 도입 확대", "품질신문", G + "QA?oc=5")],
    q("IT기획·디자인", 0): [("서비스 기획 실무 사례", "기획신문", G + "PRODUCT?oc=5")],
}


def collect(s3, feeds=FEEDS, failing=(), event=SCHEDULED):
    return C.run_collection(event, None, settings=C.Settings(bucket=BUCKET, pause_seconds=0),
                            s3_client=s3, session=FakeRssSession(feeds, failing))


def process(s3, event):
    return P.process_event(event, settings=P.ProcessorSettings(), s3_client=s3)


class NetworkGuardMixin:
    def setUp(self):
        _NETWORK_ATTEMPTS.clear()

    def tearDown(self):
        self.assertEqual(_NETWORK_ATTEMPTS, [], "테스트 중 외부 네트워크 접속 시도가 있었습니다")


class PipelineTests(NetworkGuardMixin, unittest.TestCase):
    def test_full_pipeline_with_partial_failure(self):
        s3 = InMemoryS3()
        collected = collect(s3, failing={q("백엔드·서버", 1)})
        self.assertEqual((collected["status"], collected["outcome"]), ("partial", "created"))
        raw_key = collected["key"]
        raw_before = s3.body(raw_key)
        raw = json.loads(raw_before)
        self.assertEqual([c["code"] for c in raw["categories"]],
                         [spec["code"] for spec in CATEGORIES.values()])
        self.assertEqual(len(raw["categories"]), 8)

        event = s3.take_events()
        self.assertEqual(len(event["Records"]), 1)
        result = process(s3, event)
        (record,) = result["results"]
        self.assertEqual(record["status"], "written")
        processed = json.loads(s3.body(record["processed_key"]))

        # run_id·키 대응, raw 보존
        self.assertEqual(processed["run_id"], raw["run_id"])
        self.assertEqual(processed["source_raw_key"], raw_key)
        self.assertEqual(record["processed_key"], raw_key.replace("raw/news/", "processed/news/", 1))
        self.assertEqual(s3.body(raw_key), raw_before)

        # 정규화·중복 제거·분야 병합
        by_link = {a["link_url"]: a for a in processed["articles"]}
        shared = by_link[G + "SHARED"]
        self.assertEqual(shared["field_codes"], ["data_ai", "security"])
        self.assertEqual(by_link[G + "GENAI"]["field_codes"], ["data_ai"])
        self.assertEqual(len(processed["articles"]), 8)  # 행 10건 → 링크 기준 8건
        self.assertEqual(processed["processing"]["input_rows"], 10)
        self.assertEqual(shared["title"], "AI 보안 위협 증가")
        self.assertEqual(shared["source_name"], "테스트신문")
        self.assertEqual(shared["published_at"], PUBLISHED.strftime("%Y-%m-%dT%H:%M:%SZ"))  # KST → UTC
        self.assertEqual(shared["link_key"], P.importer.link_key_of(G + "SHARED"))

        # 일부 실패 정보 전달
        self.assertEqual(processed["processing"]["status"], "partial")
        self.assertEqual(processed["collection"]["summary"], raw["collection_summary"])
        (failure,) = processed["collection"]["query_failures"]
        self.assertEqual((failure["category_code"], failure["query"], failure["error"]["type"]),
                         ("backend", q("백엔드·서버", 1), "ConnectionError"))

    def test_zero_articles(self):
        s3 = InMemoryS3()
        collected = collect(s3, feeds={})
        self.assertEqual(collected["status"], "empty")
        (record,) = process(s3, s3.take_events())["results"]
        processed = json.loads(s3.body(record["processed_key"]))
        self.assertEqual(processed["processing"]["status"], "empty")
        self.assertEqual(processed["articles"], [])
        self.assertEqual(processed["collection"]["query_failures"], [])

    def test_total_failure_stores_nothing_and_emits_no_event(self):
        s3 = InMemoryS3()
        everything = {query for spec in CATEGORIES.values() for query in spec["queries"]}
        with self.assertRaises(C.CollectionFailedError):
            collect(s3, failing=everything)
        self.assertEqual(s3.objects, {})
        self.assertEqual(s3.take_events(), {"Records": []})

    def test_duplicate_events_and_collector_retry(self):
        s3 = InMemoryS3()
        first = collect(s3)
        event = s3.take_events()
        process(s3, event)
        processed_key = first["key"].replace("raw/news/", "processed/news/", 1)
        processed_once = s3.body(processed_key)
        raw_once = s3.body(first["key"])
        s3.take_events()  # processed 저장 이벤트는 버림(트리거 대상 아님)

        # 같은 예약 실행의 재시도: 조건부 쓰기 412 → 기존 raw 보존, 새 이벤트 없음
        retry = collect(s3, feeds={})
        self.assertEqual(retry["outcome"], "already_exists")
        self.assertEqual(retry["summary"], first["summary"])
        self.assertEqual(s3.body(first["key"]), raw_once)
        self.assertEqual(s3.take_events(), {"Records": []})

        # 같은 이벤트 중복 전달: 같은 processed 바이트
        result = process(s3, {"Records": event["Records"] * 2})
        self.assertEqual([r["status"] for r in result["results"]], ["written", "written"])
        self.assertEqual(s3.body(processed_key), processed_once)

    def test_409_conflict_then_retry(self):
        s3 = InMemoryS3()
        s3.conflict_once = True
        with self.assertRaises(C.RawWriteConflictError):
            collect(s3)
        self.assertEqual(s3.objects, {})
        self.assertEqual(s3.take_events(), {"Records": []})
        retried = collect(s3)
        self.assertEqual(retried["outcome"], "created")
        (record,) = process(s3, s3.take_events())["results"]
        self.assertEqual(record["status"], "written")

    def test_processed_events_do_not_loop(self):
        """processed 저장도 ObjectCreated를 만든다고 가정하고 이벤트를 계속 다시 넣어도 끝나야 한다."""
        s3 = InMemoryS3()
        collect(s3)
        rounds = 0
        event = s3.take_events()
        while event["Records"]:
            rounds += 1
            self.assertLess(rounds, 5, "이벤트가 끝나지 않습니다")
            gets_before = len(s3.gets)
            result = process(s3, event)
            if rounds > 1:
                self.assertEqual([r.get("reason") for r in result["results"]], ["outside_raw_prefix"])
                self.assertEqual(len(s3.gets), gets_before)  # processed는 읽지도 않음
            event = s3.take_events()
        self.assertEqual(rounds, 2)

    def test_external_reupload_risk_is_visible(self):
        """남은 위험: Collector 밖에서 같은 raw 키를 조건 없이 덮어쓰면 S3는 막지 않고 Processor는 최신을 처리한다."""
        s3 = InMemoryS3()
        first = collect(s3)
        process(s3, s3.take_events())
        s3.take_events()
        tampered = json.loads(s3.body(first["key"]))
        tampered["categories"][0]["queries"][0]["articles"][0]["title"] = "외부에서 바꾼 제목"
        s3.put_object(Bucket=BUCKET, Key=first["key"],
                      Body=json.dumps(tampered, ensure_ascii=False).encode("utf-8"))  # 조건 없는 쓰기
        (record,) = process(s3, s3.take_events())["results"]
        processed = json.loads(s3.body(record["processed_key"]))
        self.assertIn("외부에서 바꾼 제목", [a["title"] for a in processed["articles"]])
        self.assertNotEqual(processed["source"]["etag"], None)  # 어떤 raw에서 나왔는지는 추적 가능


class FinalJsonContractTests(NetworkGuardMixin, unittest.TestCase):
    def test_raw_and_processed_field_types(self):
        s3 = InMemoryS3()
        collected = collect(s3, failing={q("정보보안", 2)})
        raw = json.loads(s3.body(collected["key"]))
        (record,) = process(s3, s3.take_events())["results"]
        processed = json.loads(s3.body(record["processed_key"]))
        self.assertEqual(s3.objects[(BUCKET, record["processed_key"])]["content_type"],
                         "application/json; charset=utf-8")

        self.assertEqual(list(raw), ["schema_version", "run_id", "collected_at", "categories", "collection_summary"])
        self.assertEqual(list(processed), ["schema_version", "run_id", "source_raw_key", "source",
                                           "collection", "processing", "articles"])
        types = {
            "schema_version": str, "run_id": str, "source_raw_key": str,
        }
        for field, kind in types.items():
            self.assertIsInstance(processed[field], kind, field)
        self.assertEqual(set(processed["source"]), {"bucket", "version_id", "etag", "raw_schema_version",
                                                    "collected_at"})
        self.assertEqual(set(processed["collection"]), {"summary", "categories", "query_failures"})
        processing = processed["processing"]
        for field in ("input_rows", "article_count", "multi_field_article_count"):
            self.assertIsInstance(processing[field], int)
        self.assertIn(processing["status"], {"ok", "partial", "empty"})
        self.assertIsInstance(processing["skipped"], dict)
        for failure in processed["collection"]["query_failures"]:
            self.assertEqual(set(failure), {"category_code", "query", "error"})
            self.assertEqual(set(failure["error"]), {"type", "message"})
        for article in processed["articles"]:
            self.assertEqual(set(article), {"link_key", "link_url", "link_type", "title", "source_name",
                                            "published_at", "field_codes"})
            self.assertRegex(article["link_key"], r"^[0-9a-f]{64}$")      # career_news CHECK와 같음
            self.assertRegex(article["link_url"], r"^https?://")           # career_news CHECK와 같음
            self.assertIn(article["link_type"], {"GOOGLE_NEWS_RSS", "UNVERIFIED"})
            self.assertTrue(article["title"].strip())
            self.assertLessEqual(len(article["title"]), 500)
            self.assertLessEqual(len(article["source_name"]), 200)
            self.assertRegex(article["published_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertTrue(article["field_codes"])
            self.assertEqual(article["field_codes"], sorted(set(article["field_codes"])))
            self.assertTrue(set(article["field_codes"]) <= P.importer.FIELD_CODE_VALUES)


if __name__ == "__main__":
    unittest.main()
