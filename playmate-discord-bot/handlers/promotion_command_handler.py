"""/게시글추천: 운영자가 고른 게시판 글 또는 모임을 #핫플레이메이트에 게시한다.

권한: PLAYMATE_ADMIN_ROLE_ID 역할을 가진 서버 멤버만 실행할 수 있다 (미설정이면 아무도 불가).
최소 조건(좋아요/댓글/참여 수)은 적용하지 않고, 자동 HOT 선정과는 별개다.
"""
import discord
from discord import app_commands

from services.hot_content_service import BOARD, CONTENT_LABELS, RECRUIT, HotContentService

NO_PERMISSION_MESSAGE = "이 명령은 PlayMate 운영자만 사용할 수 있습니다."


def is_admin(user, admin_role_id: int | None) -> bool:
    if admin_role_id is None:
        return False
    roles = getattr(user, "roles", None) or []
    return any(role.id == admin_role_id for role in roles)


def build_promotion_command(service: HotContentService, admin_role_id: int | None) -> app_commands.Command:
    @app_commands.command(name="게시글추천", description="게시판 글 또는 모임을 HOT PLAYMATE 채널에 게시합니다.")
    @app_commands.rename(content_type="유형", content_id="id")
    @app_commands.describe(content_type="게시판 또는 모임", content_id="게시글 ID(post_id) 또는 모임 ID(recruit_id)")
    @app_commands.choices(content_type=[
        app_commands.Choice(name=CONTENT_LABELS[BOARD], value=BOARD),
        app_commands.Choice(name=CONTENT_LABELS[RECRUIT], value=RECRUIT),
    ])
    async def recommend_post(
        interaction: discord.Interaction,
        content_type: app_commands.Choice[str],
        content_id: app_commands.Range[int, 1],
    ):
        if not is_admin(interaction.user, admin_role_id):
            await interaction.response.send_message(NO_PERMISSION_MESSAGE, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        label = CONTENT_LABELS[content_type.value]
        try:
            posted = await service.recommend(content_type.value, content_id)
        except Exception as error:
            print(f"[HOT PLAYMATE] 운영자 추천 실패 {content_type.value}:{content_id}: {error!r}")
            await interaction.followup.send("게시에 실패했습니다. 채널 설정과 Bot 권한을 확인해 주세요.", ephemeral=True)
            return
        if not posted:
            await interaction.followup.send(f"{label} {content_id}번을 찾지 못했습니다.", ephemeral=True)
            return
        await interaction.followup.send(f"{label} {content_id}번을 HOT PLAYMATE 채널에 게시했습니다.", ephemeral=True)

    return recommend_post
