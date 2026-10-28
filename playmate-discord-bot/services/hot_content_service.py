"""🔥 HOT PLAYMATE: 운영자 수동 추천(/게시글추천)을 HOT 채널에 게시한다.

좋아요·댓글·참여자 점수로 고르던 자동 선정(13:00, 19:00)은 제거했다. 팀원이 별도 HOT 게시판을
만들고 있어, 그 API·DB 구조가 확정되면 그때 연동한다 (지금은 자동 게시가 없다).
Embed에는 PlayMate 웹 상세 페이지 링크를 붙인다 (PLAYMATE_WEB_BASE_URL이 없으면 링크 없이 게시).
"""
from typing import Any

import discord

from config import HOT_CHANNEL_ID, WEB_BASE_URL
from repositories.content_repository import ContentRepository
from repositories.meeting_repository import call
from services.web_links import board_post_url, career_post_url, recruit_url

BOARD = "BOARD"
RECRUIT = "RECRUIT"
CAREER = "CAREER"
CONTENT_LABELS = {BOARD: "게시판", RECRUIT: "모임", CAREER: "취업"}
# career_posts.category_code -> 웹 화면의 게시판 이름 (pages/career/CareerPage.jsx CATEGORIES)
CAREER_CATEGORY_LABELS = {
    "reviews": "취준 도감",
    "talk": "커리어 톡톡",
    "lounge": "현직자 라운지",
    "lab": "커리어 연구소",
}
HOT_TITLE = "🔥 HOT PLAYMATE"
HOT_COLOR = 0xFF5A36
BODY_PREVIEW_LENGTH = 200
LINK_LABEL = "PlayMate에서 보기"


def _preview(text: str | None) -> str:
    text = " ".join((text or "").split())
    if len(text) <= BODY_PREVIEW_LENGTH:
        return text
    return text[:BODY_PREVIEW_LENGTH - 1] + "…"


def content_url(content_type: str, content: dict[str, Any], base_url: str | None = WEB_BASE_URL) -> str | None:
    """콘텐츠 종류와 조회 결과로 웹 상세 페이지 주소를 만든다. 만들 수 없으면 None."""
    if content_type == BOARD:
        return board_post_url(base_url, content.get("board_id"), content.get("post_id"))
    if content_type == RECRUIT:
        return recruit_url(base_url, content.get("recruit_id"))
    if content_type == CAREER:
        return career_post_url(base_url, content.get("category_code"), content.get("post_id"))
    return None


def build_hot_embed(content_type: str, content: dict[str, Any], url: str | None = None) -> discord.Embed:
    """HOT PLAYMATE 게시 형식. 운영자 추천 여부와 작성자는 표시하지 않는다."""
    title = (content.get("title") or "").strip() or "(제목 없음)"
    embed = discord.Embed(title=HOT_TITLE, color=HOT_COLOR, url=url)
    embed.add_field(name=CONTENT_LABELS[content_type], value=title[:1024], inline=False)
    preview = _preview(content.get("body"))
    if preview:
        embed.add_field(name="내용", value=preview, inline=False)
    if content_type == BOARD:
        if content.get("board_name"):
            embed.add_field(name="게시판", value=content["board_name"], inline=True)
        embed.add_field(name="댓글", value=str(content.get("comment_count") or 0), inline=True)
    elif content_type == CAREER:
        category = CAREER_CATEGORY_LABELS.get(content.get("category_code"))
        if category:
            embed.add_field(name="게시판", value=category, inline=True)
        embed.add_field(name="댓글", value=str(content.get("comment_count") or 0), inline=True)
    else:
        if content.get("category"):
            embed.add_field(name="카테고리", value=str(content["category"]), inline=True)
        members = str(content.get("member_count") or 0)
        if content.get("capacity"):
            members = f"{members} / {content['capacity']}"
        embed.add_field(name="참여 멤버", value=members, inline=True)
    if url:
        embed.add_field(name="바로가기", value=f"[{LINK_LABEL}]({url})", inline=False)
    return embed


class HotContentService:
    def __init__(self, client: discord.Client, repository: ContentRepository,
                 channel_id: int | None = HOT_CHANNEL_ID, base_url: str | None = WEB_BASE_URL):
        self.client = client
        self.repository = repository
        self.channel_id = channel_id
        self.base_url = base_url

    async def _channel(self):
        if self.channel_id is None:
            return None
        return self.client.get_channel(self.channel_id) or await self.client.fetch_channel(self.channel_id)

    async def load_content(self, content_type: str, content_id: int) -> dict[str, Any] | None:
        if content_type == BOARD:
            return await call(self.repository.get_board_post, content_id)
        if content_type == RECRUIT:
            return await call(self.repository.get_recruit, content_id)
        if content_type == CAREER:
            return await call(self.repository.get_career_post, content_id)
        return None

    async def publish(self, content_type: str, content: dict[str, Any]) -> None:
        channel = await self._channel()
        if channel is None:
            raise RuntimeError("PLAYMATE_HOT_CHANNEL_ID가 설정되지 않았습니다.")
        url = content_url(content_type, content, self.base_url)
        await channel.send(embed=build_hot_embed(content_type, content, url))

    async def recommend(self, content_type: str, content_id: int) -> bool:
        """운영자 추천: 최소 조건 없이 게시한다. 대상이 없으면 False. 중복 추천 허용, 이력 저장 없음."""
        content = await self.load_content(content_type, content_id)
        if content is None:
            return False
        await self.publish(content_type, content)
        return True
