"""취업게시판 신규 글 자동 공지: 매일 18:00 (Asia/Seoul) #취업-소식 채널에 게시한다 (DM 아님).

대상은 취준 도감(reviews)·커리어 연구소(lab)의 공개·미삭제 신규 글이며, 오래된 글부터 하루 최대 5개다.
남은 글은 다음 날 이어서 공지한다. 공지 이력은 DB(career_discord_announcements)에 남아 재시작 후에도 유지된다.

순서: 테이블·웹 주소·채널 확인 -> DB에서 선점(PENDING) -> 글마다 전송 -> SENT / FAILED 기록.
  - 테이블(013 마이그레이션)이 없거나 웹 주소가 없거나 채널을 못 찾으면 아무것도 선점·전송하지 않는다.
  - 전송에 실패한 글은 FAILED로 남겨 다음 실행에서 다시 시도한다 (성공으로 기록하지 않는다).
  - 전송 후 SENT 저장이 실패하면 PENDING으로 남고 자동 재시도하지 않는다 (같은 글 중복 공지 방지).
"""
from datetime import datetime
from typing import Any

import discord
from discord.ext import tasks

from config import (
    CAREER_NOTICE_CATEGORIES,
    CAREER_NOTICE_DAILY_LIMIT,
    CAREER_NOTICE_MAX_ATTEMPTS,
    CAREER_NOTICE_TIME,
    KST,
    WEB_BASE_URL,
)
from repositories.career_notice_repository import CareerNoticeRepository
from repositories.meeting_repository import call
from services.hot_content_service import CAREER_CATEGORY_LABELS
from services.web_links import career_post_url

NOTICE_COLOR = 0x2F80ED
TITLE_LIMIT = 200
LINK_LABEL = "PlayMate에서 보기"


def build_notice_embed(post: dict[str, Any], url: str) -> discord.Embed:
    """제목과 링크만 담는다. 본문·작성자는 넣지 않는다 (익명 글 보호, 메시지 길이 제한)."""
    title = " ".join((post.get("title") or "").split()) or "(제목 없음)"
    if len(title) > TITLE_LIMIT:
        title = title[:TITLE_LIMIT - 1] + "…"
    board = CAREER_CATEGORY_LABELS.get(post.get("category_code"), "취업게시판")
    embed = discord.Embed(title=title, url=url, color=NOTICE_COLOR)
    embed.set_author(name=f"📢 새 취업 글 · {board}")
    embed.description = f"[{LINK_LABEL}]({url})"
    return embed


class CareerNoticeService:
    def __init__(self, client: discord.Client, repository: CareerNoticeRepository, channel_id: int | None,
                 base_url: str | None = WEB_BASE_URL, daily_limit: int = CAREER_NOTICE_DAILY_LIMIT,
                 max_attempts: int = CAREER_NOTICE_MAX_ATTEMPTS):
        self.client = client
        self.repository = repository
        self.channel_id = channel_id
        self.base_url = base_url
        self.daily_limit = daily_limit
        self.max_attempts = max_attempts

    async def _channel(self):
        if self.channel_id is None:
            return None
        return self.client.get_channel(self.channel_id) or await self.client.fetch_channel(self.channel_id)

    async def run(self, now: datetime) -> int:
        """한 번 공지하고 성공한 글 수를 돌려준다. 신규 글이 없으면 아무것도 보내지 않는다."""
        if not await call(self.repository.available):
            print("[취업 공지] career_discord_announcements 테이블이 없어 건너뜁니다 (database/sql/013 적용 필요).")
            return 0
        if not self.base_url:
            print("[취업 공지] PLAYMATE_WEB_BASE_URL이 없거나 사용할 수 없어 공지하지 않습니다 (링크 없는 공지 금지).")
            return 0
        try:
            channel = await self._channel()
        except Exception as error:
            print(f"[취업 공지] 채널 조회 실패, 공지하지 않습니다: {error!r}")
            return 0
        if channel is None:
            print("[취업 공지] PLAYMATE_CAREER_CHANNEL_ID가 없어 공지하지 않습니다.")
            return 0

        stuck = await call(self.repository.count_stuck_pending)
        if stuck:
            print(f"[취업 공지] 결과가 저장되지 않은 PENDING {stuck}건: 중복 방지를 위해 자동 재시도하지 않습니다. 확인 필요.")

        today = now.astimezone(KST).date()
        posts = await call(self.repository.claim_due, today, self.daily_limit, self.max_attempts,
                           CAREER_NOTICE_CATEGORIES)
        sent = 0
        for post in posts:
            post_id = post["post_id"]
            category = post.get("category_code")
            url = career_post_url(self.base_url, category, post_id) if category in CAREER_NOTICE_CATEGORIES else None
            if url is None:
                await self._fail(post_id, f"공지 대상 게시판이 아니거나 상세 링크를 만들 수 없음: {category}")
                continue
            try:
                message = await channel.send(embed=build_notice_embed(post, url),
                                             allowed_mentions=discord.AllowedMentions.none())
            except Exception as error:
                await self._fail(post_id, f"전송 실패: {error!r}")
                continue
            sent += 1
            try:
                await call(self.repository.mark_sent, post_id, channel.id, message.id)
            except Exception as error:
                # 이미 게시되었으므로 PENDING으로 남겨 자동 재공지를 막는다.
                print(f"[취업 공지] 게시 후 SENT 저장 실패 post_id={post_id}: {error!r}")
        if posts:
            print(f"[취업 공지] {today} 공지 {sent}/{len(posts)}건")
        return sent

    async def _fail(self, post_id: int, error: str) -> None:
        print(f"[취업 공지] post_id={post_id} {error}")
        try:
            await call(self.repository.mark_failed, post_id, error)
        except Exception as save_error:
            print(f"[취업 공지] FAILED 저장 실패 post_id={post_id}: {save_error!r}")


def create_career_notice_task(client: discord.Client, service: CareerNoticeService):
    """매일 CAREER_NOTICE_TIME(18:00 KST)에 한 번 실행한다. 예외가 나도 다음 날 다시 실행된다."""

    @tasks.loop(time=CAREER_NOTICE_TIME)
    async def career_notice_task():
        try:
            await service.run(datetime.now(KST))
        except Exception as error:
            print(f"[취업 공지] 실행 실패: {error!r}")

    @career_notice_task.before_loop
    async def before_career_notice():
        await client.wait_until_ready()

    return career_notice_task
