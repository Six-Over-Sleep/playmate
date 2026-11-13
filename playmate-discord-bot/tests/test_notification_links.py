"""댓글·대댓글 DM의 원본 게시글 링크 테스트 (Issue #115).

1부(mock): URL 규칙(web_links.notification_post_url), DM 문구, 링크가 없을 때의 정상 발송, 상태 전이를 확인한다.
2부(DB): 일회용 로컬 PostgreSQL에 전용 데이터베이스를 만들어 PostgresNotificationRepository의 실제 JOIN 결과와
         게시판·모임·취업 글의 링크, 삭제된 글, DM 동의, 실패 재시도를 확인한다 (PLAYMATE_TEST_PG_DSN 필요).
실제 Discord나 공용 DB에는 연결하지 않으며, 예시 도메인은 가짜(playmate.example.test)다.
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DISCORD_BOT_TOKEN"] = "verification-only"
os.environ["DISCORD_GUILD_ID"] = "1"
# 로컬 .env의 운영 값이 테스트에 섞이지 않게 비운다 (환경변수가 .env보다 우선). 웹 주소는 각 시험에서 직접 지정한다.
for _name in ("PLAYMATE_WEB_BASE_URL", "PLAYMATE_TEST_MODE", "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD",
              "DB_NAME", "DB_SSLMODE"):
    os.environ[_name] = ""

import discord

import config
import services.notification_service as notification_service
from services.notification_service import LINK_LABEL, NotificationService, build_dm_message
from services.web_links import notification_post_url

BASE = "https://playmate.example.test"
DSN = os.environ.get("PLAYMATE_TEST_PG_DSN")
checks = 0


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


def api_error(kind):
    status = {"NotFound": 404, "Forbidden": 403, "HTTPException": 500}[kind]
    return getattr(discord, kind)(SimpleNamespace(status=status, reason="test"), "test")


def post(post_id, post_type=None, board_id=None, recruit_id=None, career=None):
    return {"post_id": post_id, "post_type": post_type, "post_board_id": board_id,
            "recruit_id": recruit_id, "career_category": career}


# ------------------------------------------------------------------ 1부: URL 규칙 / 문구
def test_url_rules():
    check(notification_post_url(BASE, post(10, "BOARD", board_id=3)) == f"{BASE}/board/3/posts/10", "일반 게시판 글 주소")
    check(notification_post_url(BASE, post(20, "RECRUIT", recruit_id=7)) == f"{BASE}/meetup/7",
          "모임 글의 상세는 post_id가 아니라 recruit_id (/meetup/{recruit_id})")
    for category in ("reviews", "talk", "lounge", "lab"):
        check(notification_post_url(BASE, post(30, "CAREER", career=category)) == f"{BASE}/career/{category}/30",
              f"취업 글({category}) 주소")
    check(notification_post_url(BASE, post(30, "CAREER", career="insights")) is None, "상세 화면이 없는 취업 분류는 링크를 만들지 않는다")
    check(notification_post_url(BASE, post(30, "CAREER", career="unknown")) is None, "알 수 없는 취업 분류는 추측하지 않는다")

    # 같은 ID라도 종류가 다르면 서로 다른 주소다 (종류가 섞여 같은 URL로 연결되지 않는다)
    urls = {notification_post_url(BASE, post(5, "BOARD", board_id=5)), notification_post_url(BASE, post(5, "RECRUIT", recruit_id=5)),
            notification_post_url(BASE, post(5, "CAREER", career="talk"))}
    check(len(urls) == 3 and None not in urls, "같은 ID의 게시판/모임/취업 글은 서로 다른 주소")

    # 종류를 확실히 알 수 없으면(근거 충돌, 타입 불일치, 알 수 없는 타입) 링크를 만들지 않는다
    conflicts = {
        "BOARD인데 모임 행도 있음": post(1, "BOARD", board_id=3, recruit_id=7),
        "RECRUIT인데 게시판 ID도 있음": post(1, "RECRUIT", board_id=3, recruit_id=7),
        "RECRUIT인데 모임 행이 없음": post(1, "RECRUIT"),
        "CAREER인데 게시판 ID도 있음": post(1, "CAREER", board_id=3, career="talk"),
        "CAREER인데 취업 행이 없음": post(1, "CAREER"),
        "BOARD인데 게시판 ID가 없음": post(1, "BOARD"),
        "알 수 없는 post_type": post(1, "NOTICE", board_id=3),
        "타입 없고 근거 없음": post(1),
        "타입 없고 근거 둘": post(1, None, board_id=3, recruit_id=7),
    }
    for label, value in conflicts.items():
        check(notification_post_url(BASE, value) is None, f"{label}: 추측하지 않고 링크 없음")
    check(notification_post_url(BASE, post(10, None, board_id=3)) == f"{BASE}/board/3/posts/10", "타입이 비어 있고 근거가 하나면 사용")
    check(notification_post_url(BASE, post(10, " board ", board_id=3)) == f"{BASE}/board/3/posts/10", "post_type 공백/대소문자 정규화")

    # 잘못된 ID / 기본 주소 없음
    for bad in (0, -1, "abc", None, True):
        check(notification_post_url(BASE, post(bad, "BOARD", board_id=3)) is None, f"잘못된 post_id {bad!r}")
        check(notification_post_url(BASE, post(10, "BOARD", board_id=bad)) is None, f"잘못된 board_id {bad!r}")
        check(notification_post_url(BASE, post(10, "RECRUIT", recruit_id=bad)) is None, f"잘못된 recruit_id {bad!r}")
    check(notification_post_url(None, post(10, "BOARD", board_id=3)) is None and notification_post_url("", post(10, "BOARD", board_id=3)) is None,
          "기본 주소가 없으면 링크 없음")


def test_base_url_policy():
    """PLAYMATE_WEB_BASE_URL 처리 정책(기존 config 규칙)이 그대로인지 확인한다."""
    parse = config._web_base_url
    check(parse(f"{BASE}/", allow_local=False) == BASE, "끝의 /는 제거")
    check(parse("", allow_local=False) is None and parse(None, allow_local=False) is None, "미설정이면 링크 없음")
    check(parse("ftp://example.test", allow_local=False) is None and parse("playmate.example.test", allow_local=False) is None,
          "http(s)가 아니면 링크 없음")
    check(parse("http://localhost:5173", allow_local=False) is None and parse("http://127.0.0.1:5173", allow_local=False) is None,
          "운영(테스트 모드 아님)에서는 localhost 링크 금지")
    check(parse("http://localhost:5173", allow_local=True) == "http://localhost:5173", "테스트 모드에서는 localhost 허용")
    check(config.WEB_BASE_URL is None, "테스트 기본 환경에는 웹 주소가 설정되어 있지 않다")


def notification(kind="COMMENT", **changes):
    value = {"notification_id": 1, "notification_type": kind, "receiver_member_id": 2, "actor_member_id": 3,
             "post_id": 10, "comment_id": 100, "retry_count": 0, "receiver_discord_id": "2002", "receiver_dm_opt_in": None,
             "post_title": "예시 글", "target_missing": False, "post_type": "BOARD", "post_board_id": 3,
             "recruit_id": None, "career_category": None}
    value.update(changes)
    return value


def test_message_format():
    comment = notification("COMMENT")
    reply = notification("REPLY")
    old_comment = "💬 내 게시글에 새 댓글이 달렸어요.\n게시글: 예시 글"
    old_reply = "↪️ 내 댓글에 새 답글이 달렸어요.\n게시글: 예시 글"
    check(build_dm_message(comment) == old_comment and build_dm_message(reply) == old_reply,
          "링크가 없을 때의 DM은 기존 문구와 같다 (제목/내용 유지)")
    url = f"{BASE}/board/3/posts/10"
    check(build_dm_message(comment, url) == f"{old_comment}\n{LINK_LABEL}: {url}", "COMMENT DM 끝에 링크 한 줄만 추가")
    check(build_dm_message(reply, url) == f"{old_reply}\n{LINK_LABEL}: {url}", "REPLY DM 끝에 링크 한 줄만 추가")
    check(build_dm_message(notification("COMMENT", post_title=None), url) == f"💬 내 게시글에 새 댓글이 달렸어요.\n{LINK_LABEL}: {url}",
          "제목이 없어도 링크는 붙는다")
    check(build_dm_message(notification("REACTION"), url) is None, "REACTION은 여전히 지원하지 않는다 (링크가 있어도 SKIPPED 대상)")


class FakeNotificationRepo:
    """상태 변경만 기록하는 가짜 저장소 (mock 시험용)."""

    def __init__(self):
        self.calls = []

    def mark_sent(self, notification_id):
        self.calls.append(("SENT", notification_id))
        return True

    def mark_skipped(self, notification_id, reason):
        self.calls.append(("SKIPPED", notification_id, reason))
        return True

    def record_failure(self, notification_id, error, max_attempts):
        self.calls.append(("FAIL", notification_id, error))
        return "PENDING"


def fake_client(send_error=None, fetch_error=None):
    user = SimpleNamespace(send=AsyncMock(side_effect=send_error))
    client = SimpleNamespace(get_user=lambda discord_id: None,
                             fetch_user=AsyncMock(side_effect=fetch_error, return_value=user))
    return client, user


async def test_delivery_mock():
    cases = (
        ("일반 게시판 댓글", notification("COMMENT"), f"{BASE}/board/3/posts/10"),
        ("일반 게시판 대댓글", notification("REPLY", comment_id=101), f"{BASE}/board/3/posts/10"),
        ("모임 댓글", notification("COMMENT", post_id=20, post_type="RECRUIT", post_board_id=None, recruit_id=7), f"{BASE}/meetup/7"),
        ("모임 대댓글", notification("REPLY", post_id=20, post_type="RECRUIT", post_board_id=None, recruit_id=7), f"{BASE}/meetup/7"),
        ("취업 댓글", notification("COMMENT", post_id=30, post_type="CAREER", post_board_id=None, career_category="talk"), f"{BASE}/career/talk/30"),
        ("취업 대댓글", notification("REPLY", post_id=30, post_type="CAREER", post_board_id=None, career_category="lab"), f"{BASE}/career/lab/30"),
    )
    for label, value, expected in cases:
        repo, (client, user) = FakeNotificationRepo(), fake_client()
        status = await NotificationService(client, repo, base_url=BASE).deliver(value)
        sent = user.send.await_args.args[0]
        check(status == "SENT" and repo.calls == [("SENT", 1)], f"{label}: DM 발송 후 SENT")
        check(sent.endswith(f"\n{LINK_LABEL}: {expected}") and sent.startswith(build_dm_message(value)),
              f"{label}: 기존 문구 뒤에 올바른 원본 링크")

    # 기본 주소가 없으면 링크만 생략하고 DM은 정상 발송 (기존과 같은 문구)
    for base in (None, ""):
        repo, (client, user) = FakeNotificationRepo(), fake_client()
        status = await NotificationService(client, repo, base_url=base).deliver(notification("COMMENT"))
        check(status == "SENT" and user.send.await_args.args[0] == build_dm_message(notification("COMMENT")),
              f"기본 주소 {base!r}: 링크 없이 정상 발송")

    # 링크 생성에서 예외가 나도 DM은 나간다
    original = notification_service.notification_post_url
    notification_service.notification_post_url = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        repo, (client, user) = FakeNotificationRepo(), fake_client()
        status = await NotificationService(client, repo, base_url=BASE).deliver(notification("COMMENT"))
    finally:
        notification_service.notification_post_url = original
    check(status == "SENT" and user.send.await_args.args[0] == build_dm_message(notification("COMMENT")), "링크 생성 오류에도 DM 정상 발송")

    # 종류를 알 수 없는 글: 링크 없이 발송
    repo, (client, user) = FakeNotificationRepo(), fake_client()
    status = await NotificationService(client, repo, base_url=BASE).deliver(notification("COMMENT", post_type="NOTICE"))
    check(status == "SENT" and LINK_LABEL not in user.send.await_args.args[0], "종류를 알 수 없는 글은 링크 없이 발송")

    # 건너뛰는 경우는 링크와 무관하게 그대로: 삭제된 글, DM 꺼짐, 본인 알림, REACTION
    skips = (
        ("삭제/없는 글", notification("COMMENT", target_missing=True), "대상 없음"),
        ("DM 꺼짐", notification("COMMENT", receiver_dm_opt_in=False), "DM 알림 꺼짐"),
        ("본인 알림", notification("COMMENT", actor_member_id=2), "본인 알림"),
        ("Discord 계정 없음", notification("COMMENT", receiver_discord_id=None), "Discord 계정 없음"),
        ("REACTION", notification("REACTION"), "지원하지 않는 알림 종류: REACTION"),
    )
    for label, value, reason in skips:
        repo, (client, user) = FakeNotificationRepo(), fake_client()
        status = await NotificationService(client, repo, base_url=BASE).deliver(value)
        check(status == "SKIPPED" and repo.calls == [("SKIPPED", 1, reason)] and user.send.await_count == 0,
              f"{label}: DM 없이 SKIPPED({reason})")
    for opt_in in (True, None):
        repo, (client, user) = FakeNotificationRepo(), fake_client()
        status = await NotificationService(client, repo, base_url=BASE).deliver(notification("COMMENT", receiver_dm_opt_in=opt_in))
        check(status == "SENT" and LINK_LABEL in user.send.await_args.args[0], f"DM 동의 {opt_in!r}: 발송(링크 포함)")

    # Discord 오류: Forbidden / 기타 오류는 PENDING 재시도 기록, NotFound는 SKIPPED
    for label, error in (("Forbidden", api_error("Forbidden")), ("HTTPException", api_error("HTTPException"))):
        repo, (client, user) = FakeNotificationRepo(), fake_client(send_error=error)
        status = await NotificationService(client, repo, base_url=BASE).deliver(notification("COMMENT"))
        check(status == "PENDING" and repo.calls[0][0] == "FAIL", f"DM 전송 {label}: 실패 기록(재시도)")
    repo, (client, user) = FakeNotificationRepo(), fake_client(fetch_error=api_error("NotFound"))
    status = await NotificationService(client, repo, base_url=BASE).deliver(notification("COMMENT"))
    check(status == "SKIPPED" and repo.calls == [("SKIPPED", 1, "Discord 사용자 없음")], "사용자 조회 NotFound: SKIPPED")


# ------------------------------------------------------------------ 2부: 일회용 PostgreSQL
SCHEMA = """
CREATE TABLE members (member_id bigint PRIMARY KEY, discord_id varchar(30), external_dm_opt_in boolean);
CREATE TABLE posts (post_id bigint PRIMARY KEY, board_id bigint, post_type varchar(20), title varchar(200),
                    deleted_at timestamp);
CREATE TABLE comments (comment_id bigint PRIMARY KEY, post_id bigint, parent_comment_id bigint, deleted_at timestamp);
CREATE TABLE recruits (recruit_id bigint PRIMARY KEY, post_id bigint NOT NULL UNIQUE);
CREATE TABLE career_posts (post_id bigint PRIMARY KEY, category_code varchar(20));
CREATE TABLE notifications (
  notification_id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, receiver_member_id bigint, actor_member_id bigint,
  notification_type varchar(20), post_id bigint, comment_id bigint, status varchar(20) NOT NULL DEFAULT 'PENDING',
  retry_count int NOT NULL DEFAULT 0, created_at timestamp NOT NULL DEFAULT now(), sent_at timestamp,
  last_attempt_at timestamp, error_message text);
"""
TEST_DB = "pm_notification_links"


def local_dsn_parts():
    from psycopg.conninfo import conninfo_to_dict

    parts = conninfo_to_dict(DSN)
    if parts.get("host") not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("일회용 로컬 DB(127.0.0.1/localhost/::1)에서만 실행합니다. 접속하지 않고 중단합니다.")
    return parts


async def test_postgres():
    import psycopg

    from repositories.db import Database
    from repositories.notification_repository import PostgresNotificationRepository

    parts = local_dsn_parts()
    admin = psycopg.connect(**parts, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {TEST_DB}")
    test_parts = {**parts, "dbname": TEST_DB}
    conn = psycopg.connect(**test_parts, autocommit=True)
    conn.execute(SCHEMA)
    repo = PostgresNotificationRepository(Database(lambda: psycopg.connect(**test_parts, autocommit=True)))

    # 회원: 1 작성자(DM 동의 NULL), 2 댓글 작성자(동의 true), 3 DM 끈 회원, 4 Discord 계정 없는 회원
    conn.execute("INSERT INTO members VALUES (1,'1001',NULL),(2,'1002',true),(3,'1003',false),(4,NULL,true)")
    posts = [  # (post_id, board_id, post_type, title, deleted)
        (10, 3, "BOARD", "게시판 글", False), (20, None, "RECRUIT", "모임 글", False), (30, None, "CAREER", "취준 도감 글", False),
        (31, None, "CAREER", "톡톡 글", False), (32, None, "CAREER", "라운지 글", False), (33, None, "CAREER", "연구소 글", False),
        (34, None, "CAREER", "인사이트 글", False), (50, 3, "BOARD", "삭제된 글", True), (60, 3, "BOARD", "충돌 글", False),
        (70, 4, None, "타입 없는 글", False), (80, 3, "BOARD", "DM 끈 회원 글", False),
    ]
    for post_id, board_id, post_type, title, deleted in posts:
        conn.execute("INSERT INTO posts VALUES (%s,%s,%s,%s,%s)", (post_id, board_id, post_type, title, "2026-01-01" if deleted else None))
    conn.execute("INSERT INTO recruits VALUES (7, 20), (8, 60)")  # 60번 글은 BOARD인데 모임 행도 있다 (근거 충돌)
    for post_id, category in ((30, "reviews"), (31, "talk"), (32, "lounge"), (33, "lab"), (34, "insights")):
        conn.execute("INSERT INTO career_posts VALUES (%s,%s)", (post_id, category))

    def add(kind, post_id, receiver=1, actor=2, deleted_comment=False):
        comment_id = conn.execute("SELECT COALESCE(MAX(comment_id), 0) + 1 FROM comments").fetchone()[0]
        conn.execute("INSERT INTO comments VALUES (%s,%s,NULL,%s)", (comment_id, post_id, "2026-01-01" if deleted_comment else None))
        return conn.execute(
            "INSERT INTO notifications (receiver_member_id, actor_member_id, notification_type, post_id, comment_id) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING notification_id", (receiver, actor, kind, post_id, comment_id)).fetchone()[0]

    ids = {}
    for name, post_id in (("board", 10), ("recruit", 20), ("reviews", 30), ("talk", 31), ("lounge", 32), ("lab", 33),
                          ("insights", 34), ("conflict", 60), ("untyped", 70)):
        ids[(name, "COMMENT")] = add("COMMENT", post_id)
        ids[(name, "REPLY")] = add("REPLY", post_id, receiver=2, actor=1)
    ids["deleted_post"] = add("COMMENT", 50)
    ids["deleted_comment"] = add("COMMENT", 10, deleted_comment=True)
    ids["dm_off"] = add("COMMENT", 80, receiver=3)
    ids["no_discord"] = add("COMMENT", 10, receiver=4)
    ids["reaction"] = add("REACTION", 10)
    ids["missing_post"] = add("COMMENT", 999)

    # JOIN 결과: 알림 한 건당 한 행, 종류별 필드가 정확히 채워진다 (중복/누락 없음)
    rows = {r["notification_id"]: r for r in repo.claim_pending(500, 0)}
    total = conn.execute("SELECT count(*) FROM notifications").fetchone()[0]
    check(len(rows) == total, f"알림 {total}건이 중복/누락 없이 조회된다 ({len(rows)}건)")
    board = rows[ids[("board", "COMMENT")]]
    check((board["post_type"], board["post_board_id"], board["recruit_id"], board["career_category"]) == ("BOARD", 3, None, None),
          "게시판 글: 게시판 ID만 채워진다")
    recruit = rows[ids[("recruit", "COMMENT")]]
    check((recruit["post_type"], recruit["post_board_id"], recruit["recruit_id"], recruit["career_category"]) == ("RECRUIT", None, 7, None),
          "모임 글: recruit_id(7)가 채워진다 (post_id 20이 아님)")
    check(rows[ids[("talk", "REPLY")]]["career_category"] == "talk" and rows[ids[("lab", "COMMENT")]]["career_category"] == "lab",
          "취업 글: 카테고리가 채워진다")
    check(rows[ids["deleted_post"]]["target_missing"] and rows[ids["deleted_comment"]]["target_missing"]
          and rows[ids["missing_post"]]["target_missing"] and not board["target_missing"],
          "삭제/없는 글과 삭제된 댓글은 target_missing")

    # 전체 파이프라인: poll_once가 실제 조회 결과로 DM을 보낸다
    sent = {}

    class Recorder:
        def __init__(self, user_id):
            self.send = AsyncMock(side_effect=lambda text, _id=user_id: sent.setdefault(_id, []).append(text))

    users = {int(d): Recorder(int(d)) for d in (1001, 1002, 1003)}
    client = SimpleNamespace(get_user=lambda discord_id: users.get(discord_id), fetch_user=AsyncMock(side_effect=api_error("NotFound")))
    service = NotificationService(client, repo, base_url=BASE)
    notification_service.NOTIFICATION_RETRY_DELAY_SECONDS = 0
    for _ in range(4):  # 한 번에 최대 NOTIFICATION_BATCH_SIZE(20)건씩 처리하므로 여러 번 돌린다
        await service.poll_once()

    def status_of(notification_id):
        return conn.execute("SELECT status, error_message FROM notifications WHERE notification_id=%s", (notification_id,)).fetchone()

    def sent_to(discord_id):
        return sent.get(discord_id, [])

    def message_for(kind, name):
        """그 알림에 해당하는 DM (받는 사람의 DM 목록에서 제목으로 찾는다)."""
        titles = {"board": "게시판 글", "recruit": "모임 글", "reviews": "취준 도감 글", "talk": "톡톡 글", "lounge": "라운지 글",
                  "lab": "연구소 글", "insights": "인사이트 글", "conflict": "충돌 글", "untyped": "타입 없는 글"}
        receiver = 1001 if kind == "COMMENT" else 1002
        header = "💬 내 게시글에 새 댓글이 달렸어요." if kind == "COMMENT" else "↪️ 내 댓글에 새 답글이 달렸어요."
        found = [m for m in sent_to(receiver) if m.startswith(header) and f"게시글: {titles[name]}" in m]
        return found[0] if found else None

    expected = {
        "board": f"{BASE}/board/3/posts/10", "recruit": f"{BASE}/meetup/7", "reviews": f"{BASE}/career/reviews/30",
        "talk": f"{BASE}/career/talk/31", "lounge": f"{BASE}/career/lounge/32", "lab": f"{BASE}/career/lab/33",
        "untyped": f"{BASE}/board/4/posts/70",
    }
    for name, url in expected.items():
        for kind in ("COMMENT", "REPLY"):
            message = message_for(kind, name)
            check(message is not None and message.endswith(f"\n{LINK_LABEL}: {url}"), f"{name} {kind}: DM에 {url.replace(BASE, '')} 링크")
    for name in ("insights", "conflict"):  # 상세 화면이 없거나 근거가 충돌: 링크 없이 발송
        for kind in ("COMMENT", "REPLY"):
            message = message_for(kind, name)
            check(message is not None and LINK_LABEL not in message, f"{name} {kind}: 링크 없이 DM 발송")

    check(status_of(ids["deleted_post"])[0] == "SKIPPED" and status_of(ids["deleted_post"])[1] == "대상 없음"
          and status_of(ids["deleted_comment"])[1] == "대상 없음" and status_of(ids["missing_post"])[1] == "대상 없음",
          "삭제/존재하지 않는 글·댓글: SKIPPED(대상 없음), DM과 링크 없음")
    check(status_of(ids["dm_off"]) == ("SKIPPED", "DM 알림 꺼짐") and sent_to(1003) == [], "DM을 끈 회원: SKIPPED, DM 없음")
    check(status_of(ids["no_discord"])[1] == "Discord 계정 없음" and status_of(ids["reaction"])[1].startswith("지원하지 않는 알림 종류"),
          "Discord 계정 없음 / REACTION: SKIPPED")
    sent_count = conn.execute("SELECT count(*) FROM notifications WHERE status='SENT'").fetchone()[0]
    check(sent_count == 2 * 9 and conn.execute("SELECT count(*) FROM notifications WHERE status='PENDING'").fetchone()[0] == 0,
          "정상 알림 18건은 SENT, 처리 대기(PENDING)는 남지 않는다")

    # 기본 주소가 없으면 링크 없이 정상 발송 (SENT)
    sent.clear()
    no_link = add("COMMENT", 10)
    await NotificationService(client, repo, base_url=None).poll_once()
    check(status_of(no_link)[0] == "SENT" and len(sent_to(1001)) == 1 and LINK_LABEL not in sent_to(1001)[0],
          "기본 주소가 없으면 링크 없이 DM 정상 발송 (PostgreSQL)")

    # Discord 실패 재시도: Forbidden은 PENDING으로 남아 3회째 FAILED, 중간에 성공하면 SENT (링크 포함)
    failing_id = add("COMMENT", 10)
    users[1001].send = AsyncMock(side_effect=api_error("Forbidden"))
    states = []
    for _ in range(3):
        await service.poll_once()
        states.append(conn.execute("SELECT status, retry_count FROM notifications WHERE notification_id=%s", (failing_id,)).fetchone())
    check(states == [("PENDING", 1), ("PENDING", 2), ("FAILED", 3)], f"Forbidden 재시도: PENDING -> PENDING -> FAILED {states}")
    await service.poll_once()
    check(users[1001].send.await_count == 3, "FAILED가 된 알림은 다시 보내지 않는다")
    retry_id = add("COMMENT", 20)
    users[1001].send = AsyncMock(side_effect=[api_error("HTTPException"), None])
    await service.poll_once()
    first = conn.execute("SELECT status, retry_count FROM notifications WHERE notification_id=%s", (retry_id,)).fetchone()
    await service.poll_once()
    second = conn.execute("SELECT status, retry_count FROM notifications WHERE notification_id=%s", (retry_id,)).fetchone()
    check(first == ("PENDING", 1) and second == ("SENT", 1), "일시 오류 뒤 재시도 성공: PENDING -> SENT")
    check(users[1001].send.await_args.args[0].endswith(f"\n{LINK_LABEL}: {BASE}/meetup/7"), "재시도 때도 같은 원본 링크로 발송")
    notFound_id = add("COMMENT", 10, receiver=2, actor=1)
    users.pop(1002)
    await service.poll_once()
    check(status_of(notFound_id) == ("SKIPPED", "Discord 사용자 없음"), "사용자 조회 NotFound: SKIPPED")

    conn.close()
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.close()


async def main():
    test_url_rules()
    test_base_url_policy()
    test_message_format()
    await test_delivery_mock()
    if DSN:
        await test_postgres()
    else:
        print("PLAYMATE_TEST_PG_DSN이 없어 PostgreSQL 부분은 건너뜁니다.")
    print(f"PASS: {checks} notification link assertions passed.")


asyncio.run(main())
