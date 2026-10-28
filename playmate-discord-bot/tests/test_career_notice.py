"""취업게시판 신규 글 자동 공지 정책 검사 (mock). Discord와 DB에 연결하지 않는다.

DB 선점·재시작·동시 실행은 tests/test_career_notice_db.py (일회용 PostgreSQL)에서 확인한다.
"""
import asyncio
import os
import sys
from datetime import datetime, time, timezone
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
from services import career_notice_service as notice

BASE = "https://playmate.example.com"
NOW = datetime(2026, 10, 28, 18, 0, tzinfo=KST)
checks = 0


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


def fake_repo(posts=(), available=True, stuck=0):
    repo = Mock()
    repo.available.return_value = available
    repo.claim_due.return_value = list(posts)
    repo.count_stuck_pending.return_value = stuck
    repo.mark_sent.return_value = True
    repo.mark_failed.return_value = True
    return repo


def fake_channel(fail_ids=()):
    sent = []

    async def send(*, embed, allowed_mentions):
        if any(f"/{post_id}" in embed.url for post_id in fail_ids):
            raise discord.HTTPException(Mock(status=500), "server error")
        sent.append((embed, allowed_mentions))
        return SimpleNamespace(id=9000 + len(sent))

    return SimpleNamespace(id=60, send=AsyncMock(side_effect=send)), sent


def client_with(channel):
    client = Mock()
    client.get_channel.return_value = channel
    return client


def service(repo, channel, base_url=BASE, channel_id=60):
    return notice.CareerNoticeService(client_with(channel), repo, channel_id, base_url=base_url)


async def policy():
    check(config.CAREER_NOTICE_TIME == time(18, 0, tzinfo=KST), "실행 시각: 매일 18:00 Asia/Seoul")
    check(datetime.combine(NOW.date(), config.CAREER_NOTICE_TIME).astimezone(timezone.utc).hour == 9,
          "18:00 KST = 09:00 UTC (서버 시간대와 무관)")
    check(config.CAREER_NOTICE_CATEGORIES == ("reviews", "lab"), "대상: 취준 도감(reviews), 커리어 연구소(lab)")
    check(config.CAREER_NOTICE_DAILY_LIMIT == 5, "하루 최대 5개")
    task = notice.create_career_notice_task(Mock(), Mock())
    check(task.time == [time(18, 0, tzinfo=KST)], "discord tasks.loop 실행 시각 18:00 KST 하루 1번")
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    check("create_career_notice_task" in source and "if CAREER_CHANNEL_ID is not None:" in source,
          "bot.py: 채널 ID가 있을 때만 공지 task 등록 (feature_tasks, 재연결 시 is_running 확인)")
    check("create_hot_task" not in source, "HOT 자동 선정은 다시 추가하지 않음")


async def sends_new_posts():
    posts = [{"post_id": 11, "category_code": "reviews", "title": "삼성 서류 합격 후기"},
             {"post_id": 12, "category_code": "lab", "title": "@everyone 포트폴리오 질문 <@123>"}]
    repo = fake_repo(posts)
    channel, sent = fake_channel()
    count = await service(repo, channel).run(NOW)
    check(count == 2 and len(sent) == 2, "신규 reviews·lab 글 2건 공지")
    args = repo.claim_due.call_args.args
    check(args == (NOW.date(), 5, 3, ("reviews", "lab")), "선점 인자: KST 날짜, 하루 5개, 3회 시도, reviews/lab")
    review, lab = sent[0][0], sent[1][0]
    check(review.url == f"{BASE}/career/reviews/11" and lab.url == f"{BASE}/career/lab/12",
          "원본 URL: /career/reviews/{id}, /career/lab/{id}")
    check(review.author.name == "📢 새 취업 글 · 취준 도감" and lab.author.name == "📢 새 취업 글 · 커리어 연구소",
          "게시판 이름 표시")
    check(review.title == "삼성 서류 합격 후기" and review.description == f"[PlayMate에서 보기]({BASE}/career/reviews/11)",
          "제목 + 링크만 표시")
    check(not review.fields and "body" not in str(review.to_dict()), "본문·작성자 없음 (짧은 메시지, 익명 보호)")
    mentions = sent[1][1]
    check(isinstance(mentions, discord.AllowedMentions) and not mentions.everyone
          and mentions.users is False and mentions.roles is False, "@everyone·@here·사용자·역할 멘션 차단")
    check([c.args for c in repo.mark_sent.call_args_list] == [(11, 60, 9001), (12, 60, 9002)],
          "성공한 글만 SENT 기록 (채널·메시지 ID)")
    repo.mark_failed.assert_not_called()

    long_title = "가" * 500
    embed = notice.build_notice_embed({"post_id": 1, "category_code": "reviews", "title": long_title},
                                      f"{BASE}/career/reviews/1")
    check(len(embed.title) == notice.TITLE_LIMIT and embed.title.endswith("…"), "긴 제목은 200자로 자름")


async def no_new_posts():
    repo = fake_repo([])
    channel, sent = fake_channel()
    check(await service(repo, channel).run(NOW) == 0 and not sent, "신규 글이 없으면 아무 메시지도 보내지 않음")
    channel.send.assert_not_awaited()


async def partial_failure():
    posts = [{"post_id": i, "category_code": "reviews", "title": f"글 {i}"} for i in (21, 22, 23)]
    repo = fake_repo(posts)
    channel, sent = fake_channel(fail_ids=(22,))
    check(await service(repo, channel).run(NOW) == 2, "3건 중 1건 실패: 2건 공지")
    check([c.args[0] for c in repo.mark_sent.call_args_list] == [21, 23], "실패한 글은 SENT로 기록하지 않음")
    failed = repo.mark_failed.call_args
    check(failed.args[0] == 22 and "전송 실패" in failed.args[1], "실패한 글은 FAILED (다음 실행에서 재시도)")

    # SENT 저장 실패: 이미 게시되었으므로 FAILED로 바꾸지 않는다 (PENDING 유지 -> 재공지 없음)
    repo = fake_repo(posts[:1])
    repo.mark_sent.side_effect = RuntimeError("db down")
    channel, sent = fake_channel()
    check(await service(repo, channel).run(NOW) == 1 and len(sent) == 1, "SENT 저장 실패해도 다음 글 처리 계속")
    repo.mark_failed.assert_not_called()
    check(True, "게시 후 저장 실패는 FAILED로 바꾸지 않음 (중복 공지 방지)")


async def safe_skips():
    posts = [{"post_id": 31, "category_code": "reviews", "title": "글"}]

    repo = fake_repo(posts)
    channel, sent = fake_channel()
    check(await service(repo, channel, base_url=None).run(NOW) == 0 and not sent,
          "웹 주소 미설정: 공지하지 않음")
    repo.claim_due.assert_not_called()
    check(True, "웹 주소 미설정: 선점하지 않아 나중에 정상 공지 가능")
    check(notice.CareerNoticeService(Mock(), repo, 60).base_url == config.WEB_BASE_URL,
          "기본 주소는 PLAYMATE_WEB_BASE_URL(config.WEB_BASE_URL) 재사용")

    repo = fake_repo(posts, available=False)
    channel, sent = fake_channel()
    check(await service(repo, channel).run(NOW) == 0 and not sent, "013 테이블이 없으면 공지하지 않음")
    repo.claim_due.assert_not_called()

    repo = fake_repo(posts)
    client = Mock()
    client.get_channel.return_value = None
    client.fetch_channel = AsyncMock(side_effect=discord.Forbidden(Mock(status=403), "missing access"))
    svc = notice.CareerNoticeService(client, repo, 60, base_url=BASE)
    check(await svc.run(NOW) == 0, "채널 조회 실패: 공지하지 않음")
    repo.claim_due.assert_not_called()
    check(True, "채널 조회 실패: 선점하지 않아 시도 횟수를 쓰지 않음")

    repo = fake_repo(posts)
    channel, sent = fake_channel()
    check(await service(repo, channel, channel_id=None).run(NOW) == 0 and not sent, "채널 ID 미설정: 공지하지 않음")

    repo = fake_repo([{"post_id": 32, "category_code": "talk", "title": "다른 게시판"}])
    channel, sent = fake_channel()
    check(await service(repo, channel).run(NOW) == 0 and not sent, "링크를 만들 수 없는 글은 보내지 않음")
    check(repo.mark_failed.call_args.args[0] == 32, "링크 생성 실패는 FAILED 기록")

    repo = fake_repo([], stuck=2)
    channel, _ = fake_channel()
    await service(repo, channel).run(NOW)
    check(repo.claim_due.called, "오래된 PENDING이 있어도 새 글 공지는 계속 (해당 글만 수동 확인)")

    # 예외가 나도 task는 멈추지 않는다
    broken = Mock(run=AsyncMock(side_effect=RuntimeError("boom")))
    await notice.create_career_notice_task(Mock(), broken).coro()
    check(True, "실행 예외가 루프를 멈추지 않음")


async def main():
    await policy()
    await sends_new_posts()
    await no_new_posts()
    await partial_failure()
    await safe_skips()


asyncio.run(main())
print(f"PASS: {checks} career notice assertions passed.")
