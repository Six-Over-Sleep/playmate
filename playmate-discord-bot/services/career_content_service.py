"""취업 소식 #취업-소식 포워딩: 채용공고는 신규 즉시 + 마감 D-3 / D-1 13:00 재노출, 그 외는 신규 1회.

중복 방지는 메모리에만 둔다 (Bot 시작 이후 등록분만, 재시작하면 초기화).
취업 DB/API가 없어 저장소가 미연결(connected=False)이며, 이때 bot.py는 루프를 시작하지 않는다.
"""
from datetime import date, datetime, timedelta

import discord
from discord.ext import tasks

from config import CAREER_POLL_SECONDS, CAREER_REMINDER_DAYS, CAREER_REMINDER_TIME, KST
from repositories.career_content_repository import (
    CAREER_KIND_LABELS,
    JOB_POSTING,
    CareerContent,
    CareerContentRepository,
)
from repositories.meeting_repository import call

CAREER_COLOR = 0x2F80ED


def reminder_deadlines(today: date) -> list[date]:
    """오늘 재노출해야 하는 채용공고의 마감일 목록 (D-3, D-1)."""
    return [today + timedelta(days=days) for days in CAREER_REMINDER_DAYS]


def reminder_label(deadline: date | None, today: date) -> str | None:
    """마감일이 D-3 또는 D-1이면 'D-3' / 'D-1', 아니면 None."""
    if deadline is None:
        return None
    days = (deadline - today).days
    return f"D-{days}" if days in CAREER_REMINDER_DAYS else None


def build_career_embed(content: CareerContent, reminder: str | None = None) -> discord.Embed:
    kind = CAREER_KIND_LABELS.get(content.kind, "취업 소식")
    heading = f"⏰ {kind} 마감 {reminder}" if reminder else f"📢 새 {kind}"
    embed = discord.Embed(title=heading, description=content.title[:4096], color=CAREER_COLOR)
    if content.summary:
        embed.add_field(name="내용", value=content.summary[:1024], inline=False)
    if content.deadline is not None:
        embed.add_field(name="마감일", value=content.deadline.isoformat(), inline=True)
    return embed


class CareerContentService:
    def __init__(self, client: discord.Client, repository: CareerContentRepository,
                 channel_id: int | None, started_at: datetime | None = None):
        self.client = client
        self.repository = repository
        self.channel_id = channel_id
        self._since = started_at or datetime.now(KST)
        self._forwarded: set[tuple[str, int]] = set()
        self._reminded: set[tuple[int, date]] = set()

    async def _send(self, embed: discord.Embed) -> None:
        channel = self.client.get_channel(self.channel_id) or await self.client.fetch_channel(self.channel_id)
        await channel.send(embed=embed)

    async def forward_new(self) -> int:
        """새로 등록된 콘텐츠를 1회씩 포워딩하고 보낸 개수를 돌려준다. 한 건 실패는 다음 주기에 재시도."""
        sent = 0
        for content in await call(self.repository.list_new_contents, self._since):
            key = (content.kind, content.content_id)
            if key in self._forwarded:
                continue
            try:
                await self._send(build_career_embed(content))
            except Exception as error:
                print(f"[취업 소식] 포워딩 실패 {key}: {error!r}")
                continue
            self._forwarded.add(key)
            sent += 1
        return sent

    async def remind_deadlines(self, today: date) -> int:
        """D-3 / D-1 채용공고를 재노출하고 보낸 개수를 돌려준다. 같은 날 같은 공고는 1회만."""
        sent = 0
        for content in await call(self.repository.list_job_postings_due, reminder_deadlines(today)):
            label = reminder_label(content.deadline, today)
            key = (content.content_id, today)
            if content.kind != JOB_POSTING or label is None or key in self._reminded:
                continue
            try:
                await self._send(build_career_embed(content, label))
            except Exception as error:
                print(f"[취업 소식] 마감 재노출 실패 {content.content_id}: {error!r}")
                continue
            self._reminded.add(key)
            sent += 1
        return sent


def create_career_tasks(client: discord.Client, service: CareerContentService):
    """(신규 포워딩 루프, 13:00 마감 재노출 루프)를 만든다. 예외가 나도 루프는 유지된다."""

    @tasks.loop(seconds=CAREER_POLL_SECONDS)
    async def career_new_task():
        try:
            await service.forward_new()
        except Exception as error:
            print(f"[취업 소식] 신규 확인 실패: {error!r}")

    @tasks.loop(time=CAREER_REMINDER_TIME)
    async def career_reminder_task():
        try:
            await service.remind_deadlines(datetime.now(KST).date())
        except Exception as error:
            print(f"[취업 소식] 마감 재노출 실패: {error!r}")

    @career_new_task.before_loop
    async def before_new():
        await client.wait_until_ready()

    @career_reminder_task.before_loop
    async def before_reminder():
        await client.wait_until_ready()

    return career_new_task, career_reminder_task
