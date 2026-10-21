"""🔥 HOT PLAYMATE: 자동 게시(13:00, 19:00, 최근 24시간 후보)와 운영자 수동 추천.

임시 점수 (조회수 제외):
    게시판 = 좋아요 x 3 + 댓글 x 2           최소 조건: 좋아요 >= 2 AND 댓글 >= 2
    모임   = 좋아요 x 3 + 참여 멤버 수 x 4    최소 조건: 좋아요 >= 2 AND 참여 멤버 >= 2
13시 1위는 메모리에 기억하고, 19시 1위가 같으면 2위를 게시한다 (재시작하면 초기화).
수동 추천은 최소 조건 없이 게시하며 자동 선정 기억에 영향을 주지 않는다. 표시 형식은 같다.
좋아요 스키마 연결 전이라 지금은 자동 게시 0건이 정상이다.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import discord
from discord.ext import tasks

from config import HOT_CANDIDATE_HOURS, HOT_CHANNEL_ID, HOT_POST_TIMES, KST
from repositories.content_repository import ContentRepository
from repositories.meeting_repository import call

BOARD = "BOARD"
RECRUIT = "RECRUIT"
CONTENT_LABELS = {BOARD: "게시판", RECRUIT: "모임"}
HOT_TITLE = "🔥 HOT PLAYMATE"
HOT_COLOR = 0xFF5A36
BODY_PREVIEW_LENGTH = 200
EVENING_HOUR = 19


@dataclass(frozen=True)
class HotCandidate:
    content_type: str  # BOARD / RECRUIT
    content_id: int
    like_count: int
    comment_count: int = 0
    member_count: int = 0

    @property
    def key(self) -> tuple[str, int]:
        return (self.content_type, self.content_id)


def hot_score(candidate: HotCandidate) -> int:
    if candidate.content_type == BOARD:
        return candidate.like_count * 3 + candidate.comment_count * 2
    return candidate.like_count * 3 + candidate.member_count * 4


def is_eligible(candidate: HotCandidate) -> bool:
    if candidate.content_type == BOARD:
        return candidate.like_count >= 2 and candidate.comment_count >= 2
    return candidate.like_count >= 2 and candidate.member_count >= 2


def rank_candidates(candidates: list[HotCandidate]) -> list[HotCandidate]:
    """최소 조건을 만족한 후보를 점수 내림차순으로 정렬한다.

    동점이면 좋아요가 많은 쪽, 그다음 ID가 큰(최근) 쪽을 앞에 둔다 (임시 규칙).
    """
    eligible = [c for c in candidates if is_eligible(c)]
    return sorted(eligible, key=lambda c: (-hot_score(c), -c.like_count, -c.content_id))


class HotPicker:
    """같은 날 13시 게시물을 메모리에 기억해서 19시 중복을 피한다."""

    def __init__(self):
        self._midday: dict[date, tuple[str, int]] = {}

    def pick(self, ranked: list[HotCandidate], today: date, hour: int) -> HotCandidate | None:
        if not ranked:
            return None
        if hour < EVENING_HOUR:
            self._midday = {today: ranked[0].key}
            return ranked[0]
        if ranked[0].key == self._midday.get(today):
            return ranked[1] if len(ranked) > 1 else None
        return ranked[0]


def _preview(text: str | None) -> str:
    text = " ".join((text or "").split())
    if len(text) <= BODY_PREVIEW_LENGTH:
        return text
    return text[:BODY_PREVIEW_LENGTH - 1] + "…"


def build_hot_embed(content_type: str, content: dict[str, Any]) -> discord.Embed:
    """자동/수동 공통 게시 형식. 운영자 추천 여부는 표시하지 않는다."""
    title = (content.get("title") or "").strip() or "(제목 없음)"
    embed = discord.Embed(title=HOT_TITLE, color=HOT_COLOR)
    embed.add_field(name=CONTENT_LABELS[content_type], value=title[:1024], inline=False)
    preview = _preview(content.get("body"))
    if preview:
        embed.add_field(name="내용", value=preview, inline=False)
    if content_type == BOARD:
        if content.get("board_name"):
            embed.add_field(name="게시판", value=content["board_name"], inline=True)
        embed.add_field(name="댓글", value=str(content.get("comment_count") or 0), inline=True)
    else:
        if content.get("category"):
            embed.add_field(name="카테고리", value=str(content["category"]), inline=True)
        members = str(content.get("member_count") or 0)
        if content.get("capacity"):
            members = f"{members} / {content['capacity']}"
        embed.add_field(name="참여 멤버", value=members, inline=True)
    return embed


class HotContentService:
    def __init__(self, client: discord.Client, repository: ContentRepository,
                 channel_id: int | None = HOT_CHANNEL_ID):
        self.client = client
        self.repository = repository
        self.channel_id = channel_id
        self.picker = HotPicker()

    async def _channel(self):
        if self.channel_id is None:
            return None
        return self.client.get_channel(self.channel_id) or await self.client.fetch_channel(self.channel_id)

    async def load_content(self, content_type: str, content_id: int) -> dict[str, Any] | None:
        if content_type == BOARD:
            return await call(self.repository.get_board_post, content_id)
        if content_type == RECRUIT:
            return await call(self.repository.get_recruit, content_id)
        return None

    async def publish(self, content_type: str, content: dict[str, Any]) -> None:
        channel = await self._channel()
        if channel is None:
            raise RuntimeError("PLAYMATE_HOT_CHANNEL_ID가 설정되지 않았습니다.")
        await channel.send(embed=build_hot_embed(content_type, content))

    async def recommend(self, content_type: str, content_id: int) -> bool:
        """운영자 추천: 최소 조건 없이 게시한다. 대상이 없으면 False. 중복 추천 허용, 이력 저장 없음."""
        content = await self.load_content(content_type, content_id)
        if content is None:
            return False
        await self.publish(content_type, content)
        return True

    async def collect_candidates(self, now: datetime) -> list[HotCandidate]:
        since = now - timedelta(hours=HOT_CANDIDATE_HOURS)
        boards = await call(self.repository.list_board_candidates, since)
        recruits = await call(self.repository.list_recruit_candidates, since)
        return [*boards, *recruits]

    async def post_scheduled(self, now: datetime) -> HotCandidate | None:
        """정해진 시각의 자동 게시. 게시한 후보(없으면 None)를 돌려준다."""
        ranked = rank_candidates(await self.collect_candidates(now))
        picked = self.picker.pick(ranked, now.date(), now.hour)
        if picked is None:
            print(f"[HOT PLAYMATE] {now:%H:%M} 게시할 후보가 없습니다.")
            return None
        content = await self.load_content(picked.content_type, picked.content_id)
        if content is None:
            print(f"[HOT PLAYMATE] 후보를 찾지 못했습니다: {picked.key}")
            return None
        await self.publish(picked.content_type, content)
        return picked


def create_hot_task(client: discord.Client, service: HotContentService):
    """매일 13:00 / 19:00 (KST)에 자동 게시한다. 예외가 나도 다음 시각에 다시 실행된다."""

    @tasks.loop(time=list(HOT_POST_TIMES))
    async def hot_task():
        try:
            await service.post_scheduled(datetime.now(KST))
        except Exception as error:
            print(f"[HOT PLAYMATE] 자동 게시 실패: {error!r}")

    @hot_task.before_loop
    async def before_hot():
        await client.wait_until_ready()

    return hot_task
