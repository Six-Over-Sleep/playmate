"""/알림설정: 내 PlayMate 댓글 DM 알림을 확인하고 버튼 하나로 켜고 끈다.

응답은 본인에게만 보인다(ephemeral). 버튼을 누르면 같은 메시지를 새 상태로 갱신한다.
저장에 실패해도(DB 권한 부족 등) 해당 사용자에게만 안내하고 Bot은 계속 동작한다.
"""
import discord
from discord import app_commands

from services.notification_service import (
    MemberNotLinked,
    NotificationService,
    SettingSaveFailed,
    dm_allowed,
)

SAVE_FAILED_MESSAGE = "알림 설정 저장에 실패했습니다."
LOAD_FAILED_MESSAGE = "알림 설정을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."
NOT_LINKED_MESSAGE = (
    "PlayMate 회원 정보와 연결된 Discord 계정을 찾지 못했습니다.\n"
    "PlayMate 웹에서 Discord 로그인으로 가입한 뒤 다시 시도해 주세요."
)


def render_status(opt_in: bool | None) -> str:
    state = "켜짐 🔔" if dm_allowed(opt_in) else "꺼짐 🔕"
    return f"**PlayMate DM 알림: {state}**\n내 게시글에 댓글이 달리면 Discord DM으로 알려드려요."


def button_label(opt_in: bool | None) -> str:
    return "알림 끄기" if dm_allowed(opt_in) else "알림 켜기"


class NotificationToggleView(discord.ui.View):
    """ON/OFF 버튼 1개. 명령을 실행한 사용자만 누를 수 있다."""

    def __init__(self, service: NotificationService, owner_id: int, opt_in: bool | None):
        super().__init__(timeout=300)
        self.service = service
        self.owner_id = owner_id
        self.toggle_button = discord.ui.Button()
        self.toggle_button.callback = self.toggle
        self.add_item(self.toggle_button)
        self._show(opt_in)

    def _show(self, opt_in: bool | None) -> None:
        self.toggle_button.label = button_label(opt_in)
        self.toggle_button.style = (
            discord.ButtonStyle.secondary if dm_allowed(opt_in) else discord.ButtonStyle.primary
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    async def toggle(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            enabled = await self.service.toggle_opt_in(interaction.user.id)
        except MemberNotLinked:
            await interaction.followup.send(NOT_LINKED_MESSAGE, ephemeral=True)
            return
        except SettingSaveFailed:
            await interaction.followup.send(SAVE_FAILED_MESSAGE, ephemeral=True)
            return
        except Exception as error:
            print(f"[알림 설정] 토글 실패: {error!r}")
            await interaction.followup.send(SAVE_FAILED_MESSAGE, ephemeral=True)
            return
        self._show(enabled)
        await interaction.edit_original_response(content=render_status(enabled), view=self)


def build_notification_command(service: NotificationService) -> app_commands.Command:
    @app_commands.command(name="알림설정", description="PlayMate 댓글 DM 알림을 확인하고 켜거나 끕니다.")
    async def notification_settings(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            opt_in = await service.get_opt_in(interaction.user.id)
        except MemberNotLinked:
            await interaction.followup.send(NOT_LINKED_MESSAGE, ephemeral=True)
            return
        except Exception as error:
            print(f"[알림 설정] 조회 실패: {error!r}")
            await interaction.followup.send(LOAD_FAILED_MESSAGE, ephemeral=True)
            return
        view = NotificationToggleView(service, interaction.user.id, opt_in)
        await interaction.followup.send(render_status(opt_in), view=view, ephemeral=True)

    return notification_settings
