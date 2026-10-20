"""알림 / HOT PLAYMATE / 취업 소식 정책 검사. Discord와 DB에 연결하지 않는다."""

import asyncio
import os
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DISCORD_BOT_TOKEN"] = "verification-only"
os.environ["DISCORD_GUILD_ID"] = "1"

import discord

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
    # 동의 정책: true만 허용
    check(notify.dm_allowed(True) and not notify.dm_allowed(False) and not notify.dm_allowed(None),
          "true만 알림 허용, false/NULL은 미허용")
    check(notify_cmd.button_label(True) == "알림 끄기", "ON이면 '알림 끄기'")
    check(notify_cmd.button_label(False) == "알림 켜기" and notify_cmd.button_label(None) == "알림 켜기",
          "OFF/NULL이면 '알림 켜기'")

    # 회원 조회는 discord_id를 문자열로 비교한다
    db = FakeDb(rows={("555",): {"member_id": 7, "external_dm_opt_in": None}})
    repo = PostgresNotificationRepository(db)
    service = notify.NotificationService(Mock(), repo)
    check(await service.get_opt_in(555) is None, "discord_id로 회원과 동의 값 조회")

    # NULL -> 켜짐 저장, external_dm_opt_in만 UPDATE
    check(await service.toggle_opt_in(555) is True, "NULL에서 토글하면 켜짐")
    sql, params = db.executed[-1]
    check(sql == "UPDATE members SET external_dm_opt_in = %s WHERE member_id = %s" and params == (True, 7),
          "external_dm_opt_in 컬럼만 갱신")
    db.rows[("555",)] = {"member_id": 7, "external_dm_opt_in": True}
    check(await service.toggle_opt_in(555) is False, "켜짐에서 토글하면 꺼짐")

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
        {**base, "notification_id": 3, "receiver_discord_id": "103", "receiver_dm_opt_in": None},
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
    check(skipped == {3: "DM 알림 미동의", 4: "Discord 계정 없음", 5: "본인 알림",
                      6: "대상 없음", 7: "Discord 사용자 없음"},
          "미동의 / discord_id 없음 / 본인 / 대상 없음 / Discord 사용자 없음 -> SKIPPED")
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


async def hot_policy():
    B, R = hot.BOARD, hot.RECRUIT
    check(hot.hot_score(hot.HotCandidate(B, 1, like_count=2, comment_count=3)) == 12, "게시판 점수 = 좋아요x3 + 댓글x2")
    check(hot.hot_score(hot.HotCandidate(R, 1, like_count=2, member_count=3)) == 18, "모임 점수 = 좋아요x3 + 멤버x4")
    check(not hot.is_eligible(hot.HotCandidate(B, 1, like_count=1, comment_count=9)), "게시판 좋아요 < 2 제외")
    check(not hot.is_eligible(hot.HotCandidate(B, 1, like_count=9, comment_count=1)), "게시판 댓글 < 2 제외")
    check(not hot.is_eligible(hot.HotCandidate(R, 1, like_count=9, member_count=1)), "모임 멤버 < 2 제외")
    check(hot.is_eligible(hot.HotCandidate(R, 1, like_count=2, member_count=2)), "모임 경계값 포함")

    top = hot.HotCandidate(R, 7, like_count=5, member_count=5)      # 35
    second = hot.HotCandidate(B, 3, like_count=5, comment_count=5)  # 25
    ranked = hot.rank_candidates([second, hot.HotCandidate(B, 9, like_count=1, comment_count=1), top])
    check(ranked == [top, second], "최소 조건 통과 후보만 점수순 정렬")

    picker = hot.HotPicker()
    today = date(2026, 10, 19)
    check(picker.pick(ranked, today, 13) == top, "13시: TOP 1")
    check(picker.pick(ranked, today, 19) == second, "19시 TOP 1이 13시와 같으면 TOP 2")
    check(picker.pick([top], today, 19) is None, "TOP 2가 없으면 게시하지 않음")
    check(picker.pick([second, top], today, 19) == second, "19시 TOP 1이 다르면 TOP 1")
    check(picker.pick(ranked, date(2026, 10, 20), 19) == top, "다른 날에는 13시 기억을 쓰지 않음")
    check(hot.HotPicker().pick(ranked, today, 19) == top, "재시작(기억 없음) 후 19시는 TOP 1")
    check(picker.pick([], today, 13) is None, "후보 없으면 게시하지 않음")

    # 좋아요 스키마 연결 전: 자동 후보 0건, 게시 없음
    channel = SimpleNamespace(send=AsyncMock())
    client = Mock()
    client.get_channel.return_value = channel
    service = hot.HotContentService(client, PostgresContentRepository(FakeDb()), channel_id=50)
    check(await service.post_scheduled(datetime(2026, 10, 19, 13, 0, tzinfo=KST)) is None, "자동 후보 0건이면 None")
    channel.send.assert_not_awaited()
    check(True, "자동 후보 0건이면 채널에 아무것도 보내지 않음")

    # 수동 추천: 최소 조건 없이 게시, 형식은 자동과 동일
    db = FakeDb(rows={(11,): {"post_id": 11, "title": "댓글 0개 글", "body": "본문", "comment_count": 0,
                              "board_name": "자유게시판"}})
    service = hot.HotContentService(client, PostgresContentRepository(db), channel_id=50)
    check(await service.recommend(B, 11), "조건 미달 글도 운영자 추천은 게시")
    embed = channel.send.await_args.kwargs["embed"]
    check(embed.title == "🔥 HOT PLAYMATE", "제목은 🔥 HOT PLAYMATE")
    text = str(embed.to_dict())
    check("ADMIN" not in text.upper() and "운영자" not in text, "운영자 추천 표시 없음")
    check(not getattr(channel.send.await_args.kwargs.get("view"), "children", None), "상세 링크 버튼 없음")
    check(await service.recommend(B, 999) is False, "없는 글은 False")
    check(service.picker._midday == {}, "수동 추천은 자동 선정 기억에 영향 없음")


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

    check(not promo_cmd.is_admin(SimpleNamespace(roles=[SimpleNamespace(id=77)]), None),
          "PLAYMATE_ADMIN_ROLE_ID 미설정이면 아무도 실행 불가")
    check([p.display_name for p in command.parameters] == ["유형", "id"], "입력값: 유형 / ID")


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
    await hot_policy()
    await promotion_command()
    await career_policy()


asyncio.run(main())
print(f"PASS: {checks} notification / promotion / career assertions passed.")
