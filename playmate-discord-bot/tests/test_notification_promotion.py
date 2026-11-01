"""알림 / HOT PLAYMATE 수동 추천·웹 링크 / 취업 소식 정책 검사. Discord와 DB에 연결하지 않는다."""

import asyncio
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DISCORD_BOT_TOKEN"] = "verification-only"
os.environ["DISCORD_GUILD_ID"] = "1"

import discord

import config
from config import KST
from handlers import notification_command_handler as notify_cmd
from handlers import promotion_command_handler as promo_cmd
from repositories.career_content_repository import (
    JOB_POSTING,
    NEWS,
    CareerContent,
    UnconnectedCareerContentRepository,
)
from repositories.content_repository import PostgresContentRepository
from repositories.notification_repository import PostgresNotificationRepository
from services import career_content_service as career
from services import hot_content_service as hot
from services import notification_service as notify
from services import web_links

checks = 0


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


class FakeDb:
    """Database 대역: 실행한 SQL을 기록하고 정해 둔 결과를 돌려준다."""

    def __init__(self, rows=None, rowcount=1, tables=(), error=None):
        self.rows, self.rowcount, self.tables, self.error = rows or {}, rowcount, set(tables), error
        self.executed = []

    def execute(self, sql, params=(), *, fetch=None):
        self.executed.append((" ".join(sql.split()), params))
        if fetch is None:
            if self.error:
                raise self.error
            return self.rowcount
        return self.rows.get(params)

    def table_exists(self, name):
        return name in self.tables


def interaction(user_id=10, roles=()):
    response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock())
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, roles=[SimpleNamespace(id=r) for r in roles]),
        response=response, followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


async def notification_settings():
    # 동의 정책: 기본 ON, 회원이 직접 끈 false만 미허용
    check(notify.dm_allowed(True) and notify.dm_allowed(None) and not notify.dm_allowed(False),
          "true/NULL(선택 안 함)은 알림 허용, false만 미허용")
    check(notify_cmd.button_label(True) == "알림 끄기" and notify_cmd.button_label(None) == "알림 끄기",
          "ON/NULL이면 '알림 끄기'")
    check(notify_cmd.button_label(False) == "알림 켜기", "OFF면 '알림 켜기'")
    check("켜짐" in notify_cmd.render_status(None) and "꺼짐" in notify_cmd.render_status(False),
          "/알림설정 화면: NULL은 켜짐, false는 꺼짐으로 표시")

    # 회원 조회는 discord_id를 문자열로 비교한다
    db = FakeDb(rows={("555",): {"member_id": 7, "external_dm_opt_in": None}})
    repo = PostgresNotificationRepository(db)
    service = notify.NotificationService(Mock(), repo)
    check(await service.get_opt_in(555) is None, "discord_id로 회원과 동의 값 조회")

    # NULL(기본 ON) -> 꺼짐 저장, external_dm_opt_in만 UPDATE
    check(await service.toggle_opt_in(555) is False, "NULL(기본 ON)에서 토글하면 꺼짐")
    sql, params = db.executed[-1]
    check(sql == "UPDATE members SET external_dm_opt_in = %s WHERE member_id = %s" and params == (False, 7),
          "external_dm_opt_in 컬럼만 false로 갱신")
    db.rows[("555",)] = {"member_id": 7, "external_dm_opt_in": False}
    check(await service.toggle_opt_in(555) is True, "꺼짐에서 토글하면 켜짐")
    check(db.executed[-1][1] == (True, 7), "켜짐은 true로 저장")
    db.rows[("555",)] = {"member_id": 7, "external_dm_opt_in": True}
    check(await service.toggle_opt_in(555) is False, "켜짐에서 토글하면 꺼짐")

    # 사용자 설정 보존: 조회만으로는 저장하지 않고, 직접 끈 false는 false 그대로 읽는다
    off_db = FakeDb(rows={("556",): {"member_id": 8, "external_dm_opt_in": False}})
    off_service = notify.NotificationService(Mock(), PostgresNotificationRepository(off_db))
    check(await off_service.get_opt_in(556) is False and len(off_db.executed) == 1
          and off_db.executed[0][0].startswith("SELECT"),
          "/알림설정 조회는 false를 그대로 보여 주고 UPDATE하지 않음")

    # 연결된 회원이 없음
    try:
        await service.get_opt_in(999)
        check(False, "미연결 회원은 예외")
    except notify.MemberNotLinked:
        check(True, "미연결 회원은 MemberNotLinked")

    # UPDATE 권한 부족 -> SettingSaveFailed, 사용자에게 저장 실패 안내
    denied = FakeDb(rows={("555",): {"member_id": 7, "external_dm_opt_in": False}},
                    error=RuntimeError("permission denied for table members"))
    denied_service = notify.NotificationService(Mock(), PostgresNotificationRepository(denied))
    view = notify_cmd.NotificationToggleView(denied_service, owner_id=555, opt_in=False)
    event = interaction(555)
    await view.toggle(event)
    event.followup.send.assert_awaited_once_with(notify_cmd.SAVE_FAILED_MESSAGE, ephemeral=True)
    event.edit_original_response.assert_not_awaited()
    check(True, "권한 부족이면 '알림 설정 저장에 실패했습니다' 안내, 메시지는 그대로")

    # 저장 성공 -> 같은 메시지 갱신
    view = notify_cmd.NotificationToggleView(service, owner_id=555, opt_in=True)
    event = interaction(555)
    await view.toggle(event)
    check(view.toggle_button.label == "알림 켜기", "저장 후 버튼 문구 갱신")
    event.edit_original_response.assert_awaited_once()
    check(event.edit_original_response.await_args.kwargs["view"] is view, "같은 메시지를 새 상태로 갱신")
    check(not await view.interaction_check(interaction(1)), "다른 사용자는 버튼 사용 불가")

    # /알림설정 명령: 미연결 회원 안내
    command = notify_cmd.build_notification_command(service)
    event = interaction(999)
    await command.callback(event)
    event.followup.send.assert_awaited_once_with(notify_cmd.NOT_LINKED_MESSAGE, ephemeral=True)
    check(True, "미연결 회원에게 가입 안내")


class RecordingDb(FakeDb):
    """notifications SQL을 기록하고, RETURNING 쓰기에는 정해 둔 행을 돌려준다."""

    def __init__(self, returning=None, **kwargs):
        super().__init__(tables={"notifications"}, **kwargs)
        self.returning = returning
        self.write_flags = []

    def execute(self, sql, params=(), *, fetch=None, write=False):
        self.write_flags.append(write)
        if write:
            self.executed.append((" ".join(sql.split()), params))
            return self.returning
        if fetch == "all":
            self.executed.append((" ".join(sql.split()), params))
            return []
        return super().execute(sql, params, fetch=fetch)


async def notification_sql():
    db = RecordingDb(returning={"status": "PENDING"})
    repo = PostgresNotificationRepository(db)
    check(repo.claim_pending(20, 60) == [], "PENDING 0건이면 빈 목록 (정상)")
    sql, params = db.executed[-1]
    check("WHERE n.status = 'PENDING'" in sql and "ORDER BY n.created_at, n.notification_id LIMIT %s" in sql,
          "PENDING을 오래된 순으로 조회 (partial index 순서)")
    check("make_interval(secs => %s)" in sql and params == (60, 20), "실패 후 재시도 간격 적용")
    check("p.deleted_at IS NOT NULL" in sql and "c.deleted_at IS NOT NULL" in sql, "삭제된 게시글/댓글은 대상 없음")

    repo.mark_sent(1)
    sql, _ = db.executed[-1]
    check("status = 'SENT', sent_at = CURRENT_TIMESTAMP" in sql, "SENT일 때 sent_at 기록")
    repo.mark_skipped(2, "본인 알림")
    sql, params = db.executed[-1]
    check("status = 'SKIPPED'" in sql and "sent_at" not in sql and params == ("본인 알림", 2),
          "SKIPPED는 sent_at을 기록하지 않음")
    check(repo.record_failure(3, "x" * 900, 3) == "PENDING", "record_failure는 새 상태 반환")
    sql, params = db.executed[-1]
    check("retry_count = retry_count + 1" in sql
          and "CASE WHEN retry_count + 1 >= %s THEN 'FAILED' ELSE 'PENDING' END" in sql,
          "실패마다 retry_count + 1, 한도 도달 시 FAILED")
    check(len(params[0]) == 500 and params[1:] == (3, 3), "error_message 500자 제한")
    check(db.write_flags[-1] is True, "RETURNING 쓰기는 재시도하지 않음")
    writes = [sql for sql, _ in db.executed if sql.startswith("UPDATE notifications")]
    check(len(writes) == 3 and all("AND status = 'PENDING'" in w for w in writes),
          "상태 변경은 PENDING 행에만 적용")
    check(all("updated_at" not in w for w in writes), "updated_at은 SET하지 않음 (DB trigger)")


async def notification_polling():
    # 테이블 없음 -> 조용히 건너뜀
    service = notify.NotificationService(Mock(), PostgresNotificationRepository(FakeDb()))
    await service.poll_once()
    await service.poll_once()
    check(service._reported == {"missing"}, "notifications 테이블이 없으면 건너뛰고 로그는 한 번")

    base = {"notification_type": "COMMENT", "receiver_member_id": 2, "actor_member_id": 3,
            "post_id": 4, "comment_id": 5, "post_title": "첫 글", "retry_count": 0,
            "target_missing": False, "receiver_dm_opt_in": True}
    pending = [
        {**base, "notification_id": 1, "receiver_discord_id": "101"},
        {**base, "notification_id": 2, "receiver_discord_id": "102"},
        {**base, "notification_id": 3, "receiver_discord_id": "103", "receiver_dm_opt_in": False},
        {**base, "notification_id": 4, "receiver_discord_id": None},
        {**base, "notification_id": 5, "receiver_discord_id": "101", "actor_member_id": 2},
        {**base, "notification_id": 6, "receiver_discord_id": "101", "target_missing": True},
        {**base, "notification_id": 7, "receiver_discord_id": "404"},
    ]
    fake = Mock()
    fake.notifications_available.return_value = True
    fake.claim_pending.return_value = pending
    fake.record_failure.return_value = "PENDING"
    user_ok = SimpleNamespace(send=AsyncMock())
    user_blocked = SimpleNamespace(send=AsyncMock(side_effect=discord.Forbidden(Mock(status=403), "blocked")))
    client = Mock()
    client.get_user.side_effect = lambda uid: {101: user_ok, 102: user_blocked}.get(uid)
    client.fetch_user = AsyncMock(side_effect=discord.NotFound(Mock(status=404), "unknown user"))
    service = notify.NotificationService(client, fake)
    await service.poll_once()
    check(fake.claim_pending.call_args.args == (20, 60), "배치 20건, 재시도 간격 60초로 조회")
    check([c.args for c in fake.mark_sent.call_args_list] == [(1,)], "DM 성공 -> SENT")
    failure = fake.record_failure.call_args
    check(failure.args[0] == 2 and failure.args[2] == 3, "DM 실패 -> 재시도 기록 (최대 3회)")
    skipped = {c.args[0]: c.args[1] for c in fake.mark_skipped.call_args_list}
    check(skipped == {3: "DM 알림 꺼짐", 4: "Discord 계정 없음", 5: "본인 알림",
                      6: "대상 없음", 7: "Discord 사용자 없음"},
          "알림 꺼짐 / discord_id 없음 / 본인 / 대상 없음 / Discord 사용자 없음 -> SKIPPED")
    check(user_ok.send.await_count == 1 and "첫 글" in user_ok.send.await_args.args[0], "DM에 게시글 제목 포함")

    # 3회째 실패하면 FAILED (상태 결정은 저장소 SQL, 서비스는 결과를 그대로 전달)
    fake.record_failure.return_value = "FAILED"
    status = await service.deliver({**base, "notification_id": 2, "receiver_discord_id": "102", "retry_count": 2})
    check(status == "FAILED", "총 3회 실패 후 FAILED")

    # 상태 기록 실패가 다음 알림 처리를 막지 않는다
    fake.mark_sent.side_effect = RuntimeError("db down")
    fake.mark_skipped.reset_mock()
    await service.poll_once()
    check(fake.mark_skipped.call_count == 5, "한 건 저장 실패 후에도 나머지 처리")

    # 루프는 예외를 삼켜 계속 돈다
    fake.claim_pending.side_effect = RuntimeError("db down")
    task = notify.create_notification_task(client, service)
    await task.coro()
    check(True, "polling 예외가 루프를 멈추지 않음")


async def notification_reply():
    """REPLY는 부모 댓글 작성자에게 DM으로 보내고, REACTION은 #61 범위에서 제외되어 SKIPPED로 남긴다."""
    base = {"receiver_member_id": 2, "actor_member_id": 3, "post_id": 4, "comment_id": 6,
            "post_title": "첫 글", "retry_count": 0, "target_missing": False,
            "receiver_dm_opt_in": True, "receiver_discord_id": "101"}
    comment_text = notify.build_dm_message({**base, "notification_type": "COMMENT"})
    reply_text = notify.build_dm_message({**base, "notification_type": "REPLY"})
    check(comment_text == "💬 내 게시글에 새 댓글이 달렸어요.\n게시글: 첫 글", "COMMENT 문구는 기존 그대로")
    check(reply_text == "↪️ 내 댓글에 새 답글이 달렸어요.\n게시글: 첫 글", "REPLY 문구: 내 댓글에 새 답글")
    check(notify.build_dm_message({**base, "notification_type": "REPLY", "post_title": None})
          == "↪️ 내 댓글에 새 답글이 달렸어요.", "제목이 없으면 문구만")
    check(notify.build_dm_message({**base, "notification_type": "REACTION"}) is None, "REACTION DM은 보내지 않음 (#61 범위 제외)")

    fake = Mock()
    fake.record_failure.return_value = "PENDING"
    user = SimpleNamespace(send=AsyncMock())
    client = Mock()
    client.get_user.side_effect = lambda uid: {101: user}.get(uid)
    service = notify.NotificationService(client, fake)
    check(await service.deliver({**base, "notification_id": 11, "notification_type": "REPLY"}) == "SENT",
          "REPLY -> DM 전송 후 SENT (SKIPPED 아님)")
    check(fake.mark_sent.call_args.args == (11,) and user.send.await_args.args[0] == reply_text,
          "REPLY DM 본문 전송, mark_sent 호출")
    check(await service.deliver({**base, "notification_id": 12, "notification_type": "REPLY",
                                 "actor_member_id": 2}) == "SKIPPED"
          and fake.mark_skipped.call_args.args == (12, "본인 알림"), "본인 대댓글 REPLY -> SKIPPED")
    check(await service.deliver({**base, "notification_id": 13, "notification_type": "REPLY",
                                 "receiver_dm_opt_in": False}) == "SKIPPED"
          and fake.mark_skipped.call_args.args == (13, "DM 알림 꺼짐"), "DM 끈 회원 REPLY -> SKIPPED")
    check(await service.deliver({**base, "notification_id": 17, "notification_type": "COMMENT",
                                 "receiver_dm_opt_in": None}) == "SENT"
          and fake.mark_sent.call_args.args == (17,), "선택 안 한 회원(NULL)도 기본 ON -> COMMENT DM 전송")
    check(await service.deliver({**base, "notification_id": 18, "notification_type": "REPLY",
                                 "receiver_dm_opt_in": None}) == "SENT", "NULL 회원 REPLY DM 전송")
    check(await service.deliver({**base, "notification_id": 14, "notification_type": "REPLY",
                                 "target_missing": True}) == "SKIPPED"
          and fake.mark_skipped.call_args.args == (14, "대상 없음"), "삭제된 대상 REPLY -> SKIPPED")
    check(await service.deliver({**base, "notification_id": 15, "notification_type": "REACTION"}) == "SKIPPED"
          and fake.mark_skipped.call_args.args == (15, "지원하지 않는 알림 종류: REACTION"),
          "REACTION -> SKIPPED (#61 범위 제외, 타입·테이블 구조는 유지)")
    user.send.side_effect = discord.Forbidden(Mock(status=403), "blocked")
    check(await service.deliver({**base, "notification_id": 16, "notification_type": "REPLY"}) == "PENDING"
          and fake.record_failure.call_args.args[0] == 16, "REPLY DM 차단 -> 기존 재시도 정책")


async def hot_auto_removed():
    """자체 HOT 자동 선정(점수 SQL, 13:00/19:00 스케줄)은 제거되었다. 수동 /게시글추천만 남는다."""
    for name in ("HotCandidate", "HotPicker", "hot_score", "is_eligible", "rank_candidates", "create_hot_task"):
        check(not hasattr(hot, name), f"HOT 자동 선정 {name} 제거")
    check(not hasattr(hot.HotContentService, "post_scheduled"), "자동 게시 메서드 제거")
    for name in ("list_board_candidates", "list_recruit_candidates"):
        check(not hasattr(PostgresContentRepository, name), f"HOT 후보 집계 SQL {name} 제거")
    check(not hasattr(config, "HOT_POST_TIMES") and not hasattr(config, "HOT_CANDIDATE_HOURS"),
          "자동 게시 시각·후보 기간 설정 제거")
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    check("create_hot_task" not in source and "자동 게시 (13:00" not in source, "bot.py는 HOT 자동 task를 시작하지 않음")


async def web_link_policy():
    base = "https://playmate.example.com"
    check(web_links.board_post_url(base, 2, 15) == f"{base}/board/2/posts/15", "게시판: /board/{board_id}/posts/{post_id}")
    check(web_links.recruit_url(base, 8) == f"{base}/meetup/8", "모임: /meetup/{recruit_id}")
    for category in ("reviews", "talk", "lounge", "lab"):
        check(web_links.career_post_url(base, category, 31) == f"{base}/career/{category}/31",
              f"취업: /career/{category}/{{post_id}}")
    check(web_links.career_post_url(base, "insights", 31) is None, "글이 없는 채용 인사이트는 링크 없음")
    check(web_links.career_post_url(base, "jobs", 31) is None, "모르는 취업 카테고리는 링크 없음")
    check(web_links.board_post_url(None, 2, 15) is None, "기본 주소가 없으면 링크 없음")
    check(web_links.board_post_url(base, None, 15) is None and web_links.recruit_url(base, 0) is None
          and web_links.recruit_url(base, True) is None and web_links.recruit_url(base, "x") is None,
          "ID가 없거나 0 이하·숫자가 아니면 링크 없음")

    # 기본 주소 환경변수: 끝의 / 제거, http(s)만, localhost는 테스트 모드에서만
    check(config._web_base_url(" https://playmate.example.com/ ", allow_local=False) == base, "끝의 / 제거")
    check(config._web_base_url("", allow_local=False) is None and config._web_base_url(None, allow_local=True) is None,
          "비어 있으면 링크 없음")
    check(config._web_base_url("ftp://playmate.example.com", allow_local=False) is None, "http(s)가 아니면 무시")
    check(config._web_base_url("playmate.example.com", allow_local=False) is None, "scheme이 없으면 무시")
    for local in ("http://localhost:5173", "http://127.0.0.1:5173", "http://LOCALHOST", "http://[::1]:5173",
                  "http://0.0.0.0:5173"):
        check(config._web_base_url(local, allow_local=False) is None, f"운영에서는 {local} 링크 금지")
    check(config._web_base_url("http://localhost:5173", allow_local=True) == "http://localhost:5173",
          "PLAYMATE_TEST_MODE=true면 localhost 허용 (로컬 확인용)")
    check(config._web_base_url("https://localhost.playmate.example.com", allow_local=False)
          == "https://localhost.playmate.example.com", "localhost로 시작하는 실제 도메인은 허용")


async def promotion_service():
    """수동 추천: 최소 조건 없이 게시, 게시판·모임·취업 글에 웹 상세 링크를 붙인다."""
    B, R, C = hot.BOARD, hot.RECRUIT, hot.CAREER
    base = "https://playmate.example.com"
    channel = SimpleNamespace(send=AsyncMock())
    client = Mock()
    client.get_channel.return_value = channel

    db = FakeDb(rows={(11,): {"post_id": 11, "board_id": 2, "title": "댓글 0개 글", "body": "본문",
                              "comment_count": 0, "board_name": "자유게시판"}})
    service = hot.HotContentService(client, PostgresContentRepository(db), channel_id=50, base_url=base)
    check(await service.recommend(B, 11), "조건 미달 글도 운영자 추천은 게시")
    embed = channel.send.await_args.kwargs["embed"]
    check(embed.title == "🔥 HOT PLAYMATE", "제목은 🔥 HOT PLAYMATE")
    check(embed.url == f"{base}/board/2/posts/11", "게시판 추천 Embed 제목에 상세 링크")
    check(any(f.name == "바로가기" and f"({base}/board/2/posts/11)" in f.value for f in embed.fields),
          "게시판 추천에 'PlayMate에서 보기' 링크 표시")
    text = str(embed.to_dict())
    check("ADMIN" not in text.upper() and "운영자" not in text, "운영자 추천 표시 없음")
    check(await service.recommend(B, 999) is False, "없는 글은 False")
    sql = db.executed[0][0]
    check("p.board_id IS NOT NULL" in sql and "NOT EXISTS (SELECT 1 FROM recruits" in sql,
          "게시판 조회는 기존 조건 그대로 (취업 글·모집글 제외)")

    db = FakeDb(rows={(8,): {"recruit_id": 8, "title": "풋살 모임", "body": "", "member_count": 3, "capacity": 6}})
    service = hot.HotContentService(client, PostgresContentRepository(db), channel_id=50, base_url=base)
    check(await service.recommend(R, 8), "모임 추천 게시")
    embed = channel.send.await_args.kwargs["embed"]
    check(embed.url == f"{base}/meetup/8", "모임 추천 링크: /meetup/{recruit_id}")

    db = FakeDb(rows={(31,): {"post_id": 31, "category_code": "talk", "title": "이직 고민", "body": "본문",
                              "comment_count": 2}})
    service = hot.HotContentService(client, PostgresContentRepository(db), channel_id=50, base_url=base)
    check(await service.recommend(C, 31), "취업 글 추천 게시")
    embed = channel.send.await_args.kwargs["embed"]
    check(embed.url == f"{base}/career/talk/31", "취업 추천 링크: /career/{category}/{post_id}")
    fields = {f.name: f.value for f in embed.fields}
    check(fields.get("취업") == "이직 고민" and fields.get("게시판") == "커리어 톡톡" and fields.get("댓글") == "2",
          "취업 Embed: 제목·게시판 이름·댓글 수")
    sql = db.executed[0][0]
    check("JOIN career_posts cp" in sql and "p.post_type = 'CAREER'" in sql and "p.deleted_at IS NULL" in sql,
          "취업 글 조회: Backend와 같은 대상 조건 (삭제 제외)")
    check("author" not in sql and "nickname" not in sql, "취업 글 조회는 작성자를 읽지 않음 (익명 보호)")
    check(await service.recommend(C, 999) is False, "없는 취업 글은 False")

    # 기본 주소가 없으면 링크 없이 기존 형식으로 게시
    db = FakeDb(rows={(11,): {"post_id": 11, "board_id": 2, "title": "글", "body": "본문", "comment_count": 0}})
    service = hot.HotContentService(client, PostgresContentRepository(db), channel_id=50, base_url=None)
    check(await service.recommend(B, 11), "기본 주소 없이도 게시")
    embed = channel.send.await_args.kwargs["embed"]
    check(embed.url is None and all(f.name != "바로가기" for f in embed.fields), "기본 주소가 없으면 링크 없음")
    check(not getattr(channel.send.await_args.kwargs.get("view"), "children", None), "링크 버튼(View)은 쓰지 않음")

    # HOT 채널 미설정이면 게시 실패 (명령 처리에서 실패 안내)
    service = hot.HotContentService(client, PostgresContentRepository(db), channel_id=None, base_url=base)
    try:
        await service.recommend(B, 11)
        check(False, "채널 미설정은 예외")
    except RuntimeError:
        check(True, "HOT 채널 미설정이면 RuntimeError")


async def promotion_command():
    service = Mock(recommend=AsyncMock(return_value=True))
    command = promo_cmd.build_promotion_command(service, admin_role_id=77)
    board_choice = SimpleNamespace(value=hot.BOARD)

    event = interaction(roles=(1,))
    await command.callback(event, board_choice, 5)
    event.response.send_message.assert_awaited_once_with(promo_cmd.NO_PERMISSION_MESSAGE, ephemeral=True)
    service.recommend.assert_not_awaited()
    check(True, "Admin Role이 없으면 거부")

    event = interaction(roles=(77,))
    await command.callback(event, board_choice, 5)
    service.recommend.assert_awaited_once_with(hot.BOARD, 5)
    check("게시했습니다" in event.followup.send.await_args.args[0], "Admin Role이면 게시")

    event = interaction(roles=(77,))
    await command.callback(event, SimpleNamespace(value=hot.CAREER), 31)
    check(service.recommend.await_args.args == (hot.CAREER, 31)
          and event.followup.send.await_args.args[0] == "취업 31번을 HOT PLAYMATE 채널에 게시했습니다.",
          "취업 유형 추천")

    service.recommend = AsyncMock(return_value=False)
    event = interaction(roles=(77,))
    await command.callback(event, board_choice, 404)
    check(event.followup.send.await_args.args[0] == "게시판 404번을 찾지 못했습니다.", "없는 글 안내")

    service.recommend = AsyncMock(side_effect=RuntimeError("PLAYMATE_HOT_CHANNEL_ID가 설정되지 않았습니다."))
    event = interaction(roles=(77,))
    await command.callback(event, board_choice, 5)
    check("게시에 실패했습니다" in event.followup.send.await_args.args[0], "게시 실패 안내 (채널·권한 확인)")

    check(not promo_cmd.is_admin(SimpleNamespace(roles=[SimpleNamespace(id=77)]), None),
          "PLAYMATE_ADMIN_ROLE_ID 미설정이면 아무도 실행 불가")
    check([p.display_name for p in command.parameters] == ["유형", "id"], "입력값: 유형 / ID")
    choices = [(c.name, c.value) for c in command.parameters[0].choices]
    check(choices == [("게시판", "BOARD"), ("모임", "RECRUIT"), ("취업", "CAREER")], "유형 선택지: 게시판 / 모임 / 취업")


async def career_policy():
    today = date(2026, 10, 19)
    check(career.reminder_deadlines(today) == [date(2026, 10, 22), date(2026, 10, 20)], "D-3 / D-1 마감일 계산")
    check(career.reminder_label(date(2026, 10, 22), today) == "D-3", "D-3 판정")
    check(career.reminder_label(date(2026, 10, 20), today) == "D-1", "D-1 판정")
    check(career.reminder_label(date(2026, 10, 21), today) is None, "D-2는 재노출 안 함")
    check(career.reminder_label(None, today) is None, "마감일 없음은 재노출 안 함")
    check(UnconnectedCareerContentRepository.connected is False, "취업 저장소는 아직 미연결")

    created = datetime(2026, 10, 19, 9, tzinfo=KST)
    posting = CareerContent(1, JOB_POSTING, "백엔드 채용", created, deadline=date(2026, 10, 22))
    news = CareerContent(2, NEWS, "IT 뉴스", created)
    repo = Mock(list_new_contents=Mock(return_value=[posting, news]),
                list_job_postings_due=Mock(return_value=[posting]))
    channel = SimpleNamespace(send=AsyncMock())
    client = Mock()
    client.get_channel.return_value = channel
    service = career.CareerContentService(client, repo, channel_id=60, started_at=created)
    check(await service.forward_new() == 2, "신규 채용공고 / 뉴스 포워딩")
    check(await service.forward_new() == 0, "같은 콘텐츠는 1회만 포워딩")
    check(await service.remind_deadlines(today) == 1, "D-3 채용공고 재노출")
    check("D-3" in channel.send.await_args.kwargs["embed"].title, "재노출 제목에 D-3 표시")
    check(await service.remind_deadlines(today) == 0, "같은 날 같은 공고는 재노출 1회")


async def main():
    await notification_settings()
    await notification_sql()
    await notification_polling()
    await notification_reply()
    await hot_auto_removed()
    await web_link_policy()
    await promotion_service()
    await promotion_command()
    await career_policy()


asyncio.run(main())
print(f"PASS: {checks} notification / promotion / career assertions passed.")
