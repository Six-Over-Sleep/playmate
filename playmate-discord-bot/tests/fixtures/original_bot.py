import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks
from dotenv import load_dotenv


# =========================================================
# 1. 환경변수 / 기본 설정
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")


if not TOKEN:
    raise ValueError(
        "DISCORD_BOT_TOKEN이 .env에 없습니다."
    )

if not GUILD_ID:
    raise ValueError(
        "DISCORD_GUILD_ID가 .env에 없습니다."
    )


GUILD_ID = int(GUILD_ID)

# 한국 시간
KST = ZoneInfo("Asia/Seoul")


# =========================================================
# 2. PlayMate 운영 정책
# =========================================================

# 상시모임:
# 30일간 활동이 없으면 HOST에게 경고
INACTIVITY_DAYS = 30

# 경고 후 7일 동안 활동이 없으면 자동 종료
INACTIVITY_GRACE_DAYS = 7

# 일회성 모임:
# end_at 이후 24시간 동안 Discord 공간 유지 후 삭제
ONE_TIME_DELETE_GRACE_HOURS = 24


# =========================================================
# 3. 검사 주기
#
# 테스트:
#   1분마다
#
# 실서비스:
#   하루 1회
#
# 현재는 테스트용.
# 실제 서비스 배포 시 False로 변경 예정.
# =========================================================

TEST_MODE = True

CHECK_INTERVAL_SECONDS = (
    60
    if TEST_MODE
    else 60 * 60 * 24
)


# =========================================================
# 4. Discord Client
# =========================================================

intents = discord.Intents.default()

client = discord.Client(
    intents=intents
)


# =========================================================
# 5. 테스트용 데이터
#
# 실제 서비스에서는 전부 PostgreSQL 조회로 교체 예정.
#
# 아래 테스트 데이터는 Bot 기능 검증을 위한 임시 데이터이며
# 실제 서비스 코드에서는 하드코딩하지 않는다.
# =========================================================


# ---------------------------------------------------------
# 5-1. 일회성 모임
#
# 예시:
#
# TEST_ONE_TIME_MEETINGS = [
#     {
#         "recruit_id": 1,
#         "category_id": 123456789012345678,
#         "end_at":
#             datetime.now(KST)
#             - timedelta(hours=25),
#         "discord_deleted_at": None,
#     }
# ]
# ---------------------------------------------------------

TEST_ONE_TIME_MEETINGS = []


# ---------------------------------------------------------
# 5-2. 상시모임
#
# 예시:
#
# TEST_ONGOING_MEETINGS = {
#
#     123456789012345678: {
#
#         "recruit_id": 2,
#
#         "host_id":
#             123456789012345678,
#
#         "last_activity_at":
#             datetime.now(KST)
#             - timedelta(days=31),
#
#         "inactivity_warned_at": None,
#
#         "scheduled_delete_at": None,
#
#         "discord_deleted_at": None,
#     }
# }
#
# key:
# Discord category_id
# ---------------------------------------------------------

TEST_ONGOING_MEETINGS = {}


# =========================================================
# 6. 모임 Discord 공간 생성
# =========================================================

async def create_meeting_space(
    guild: discord.Guild,
    meeting_name: str,
    visibility: str = "PUBLIC",
    participant_ids: list[int] | None = None,
    create_voice_channel: bool = True,
):
    """
    PlayMate에서 생성 승인된 모임의
    Discord 공간을 생성한다.

    구조:

    📁 모임명
    ├─ # 채팅
    └─ 🔊 음성


    원칙:

    - 모임명 중복 검사는 PlayMate 백엔드/DB 담당
    - Bot은 모임명을 정규화하여
      동일 모임 여부를 판단하지 않는다.
    - 실제 서비스 중복 생성 방지는
      recruit_id ↔ Discord resource ID 기준으로 처리한다.
    """

    participant_ids = (
        participant_ids or []
    )

    visibility = (
        visibility.upper()
    )


    if visibility not in (
        "PUBLIC",
        "PRIVATE",
    ):
        raise ValueError(
            "visibility은 "
            "PUBLIC 또는 PRIVATE여야 합니다."
        )


    # -----------------------------------------------------
    # 6-1. 기본 권한
    # -----------------------------------------------------

    if visibility == "PUBLIC":

        # 비참여자:
        #
        # 채널 보기 O
        # 채팅 읽기 O
        # 채팅 쓰기 X
        # 음성 채널 보기 O
        # 음성 접속 X

        overwrites = {

            guild.default_role:
                discord.PermissionOverwrite(

                    view_channel=True,

                    read_message_history=True,

                    send_messages=False,

                    connect=False,

                    speak=False,
                )
        }


    else:

        # PRIVATE:
        #
        # 비참여자는
        # 카테고리 자체가 보이지 않는다.

        overwrites = {

            guild.default_role:
                discord.PermissionOverwrite(

                    view_channel=False,

                    read_message_history=False,

                    send_messages=False,

                    connect=False,

                    speak=False,
                )
        }


    # -----------------------------------------------------
    # 6-2. 기존 참여자 권한
    # -----------------------------------------------------

    for participant_id in participant_ids:

        try:

            member = (
                await guild.fetch_member(
                    participant_id
                )
            )


        except discord.NotFound:

            print(
                f"참여자를 찾을 수 없음: "
                f"{participant_id}"
            )

            continue


        except discord.Forbidden:

            print(
                f"참여자 조회 권한 없음: "
                f"{participant_id}"
            )

            continue


        overwrites[
            member
        ] = discord.PermissionOverwrite(

            view_channel=True,

            read_message_history=True,

            send_messages=True,

            connect=True,

            speak=True,
        )


    # -----------------------------------------------------
    # 6-3. 모임 카테고리 생성
    # -----------------------------------------------------

    category = (
        await guild.create_category(

            name=meeting_name,

            overwrites=overwrites,
        )
    )


    print(
        f"모임 카테고리 생성 완료: "
        f"{category.name} "
        f"(ID: {category.id})"
    )


    # -----------------------------------------------------
    # 6-4. 텍스트 채널 생성
    # -----------------------------------------------------

    text_channel = (
        await guild.create_text_channel(

            name="채팅",

            category=category,

            topic=(
                f"[{visibility}] "
                f"{meeting_name}"
            ),
        )
    )


    print(
        f"텍스트 채널 생성 완료: "
        f"{text_channel.name} "
        f"(ID: {text_channel.id})"
    )


    # -----------------------------------------------------
    # 6-5. 음성 채널 생성
    # -----------------------------------------------------

    voice_channel = None


    if create_voice_channel:

        voice_channel = (
            await guild.create_voice_channel(

                name="음성",

                category=category,
            )
        )


        print(
            f"음성 채널 생성 완료: "
            f"{voice_channel.name} "
            f"(ID: {voice_channel.id})"
        )


    else:

        print(
            "음성 채널 생성 안 함"
        )


    return (
        category,
        text_channel,
        voice_channel,
    )


# =========================================================
# 7. 일반 참여자 권한 부여
# =========================================================

async def grant_participant_permissions(
    guild: discord.Guild,
    category_id: int,
    participant_id: int,
):
    """
    PlayMate 모임 참여 성공 시
    Discord 사용 권한을 부여한다.

    PUBLIC / PRIVATE 관계없이
    참여자는 해당 모임 공간을 사용할 수 있다.
    """

    category = guild.get_channel(
        category_id
    )


    if category is None:

        print(
            f"카테고리를 찾을 수 없음: "
            f"{category_id}"
        )

        return False


    try:

        member = (
            await guild.fetch_member(
                participant_id
            )
        )


    except discord.NotFound:

        print(
            f"참여자를 찾을 수 없음: "
            f"{participant_id}"
        )

        return False


    except discord.Forbidden:

        print(
            f"참여자 조회 권한 없음: "
            f"{participant_id}"
        )

        return False


    participant_overwrite = (
        discord.PermissionOverwrite(

            view_channel=True,

            read_message_history=True,

            send_messages=True,

            connect=True,

            speak=True,
        )
    )


    # 카테고리 권한
    await category.set_permissions(

        member,

        overwrite=participant_overwrite,
    )


    # 하위 채널 권한
    for channel in category.channels:

        await channel.set_permissions(

            member,

            overwrite=participant_overwrite,
        )


    print(
        f"참여자 권한 부여 완료: "
        f"{member} "
        f"→ {category.name}"
    )


    return True


# =========================================================
# 8. 참여 취소 권한 회수
# =========================================================

async def remove_participant_permissions(
    guild: discord.Guild,
    category_id: int,
    participant_id: int,
    visibility: str,
):
    """
    PlayMate에서 참여 취소 시
    Discord 권한을 회수한다.

    PUBLIC:
    비참여자 상태로 되돌림
    → 읽기 O
    → 쓰기 X
    → 음성 접속 X

    PRIVATE:
    개인 권한 제거
    → @everyone 권한을 따라가므로
      비참여자는 채널을 볼 수 없음.
    """

    visibility = (
        visibility.upper()
    )


    if visibility not in (
        "PUBLIC",
        "PRIVATE",
    ):

        raise ValueError(
            "visibility은 "
            "PUBLIC 또는 PRIVATE여야 합니다."
        )


    category = guild.get_channel(
        category_id
    )


    if category is None:

        print(
            f"카테고리를 찾을 수 없음: "
            f"{category_id}"
        )

        return False


    try:

        member = (
            await guild.fetch_member(
                participant_id
            )
        )


    except discord.NotFound:

        print(
            f"참여자를 찾을 수 없음: "
            f"{participant_id}"
        )

        return False


    except discord.Forbidden:

        print(
            f"참여자 조회 권한 없음: "
            f"{participant_id}"
        )

        return False


    # -----------------------------------------------------
    # PUBLIC
    # -----------------------------------------------------

    if visibility == "PUBLIC":

        overwrite = (
            discord.PermissionOverwrite(

                view_channel=True,

                read_message_history=True,

                send_messages=False,

                connect=False,

                speak=False,
            )
        )


        await category.set_permissions(

            member,

            overwrite=overwrite,
        )


        for channel in category.channels:

            await channel.set_permissions(

                member,

                overwrite=overwrite,
            )


        print(
            f"PUBLIC 참여 취소 처리 완료: "
            f"{member} "
            f"→ 읽기만 허용"
        )


    # -----------------------------------------------------
    # PRIVATE
    # -----------------------------------------------------

    else:

        await category.set_permissions(

            member,

            overwrite=None,
        )


        for channel in category.channels:

            await channel.set_permissions(

                member,

                overwrite=None,
            )


        print(
            f"PRIVATE 참여 취소 처리 완료: "
            f"{member} "
            f"→ 접근 권한 제거"
        )


    return True


# =========================================================
# 9. HOST 권한 부여
# =========================================================

async def grant_host_permissions(
    guild: discord.Guild,
    category_id: int,
    host_id: int,
):
    """
    PlayMate recruit_members.role = HOST인 사용자에게
    Discord HOST 권한을 부여한다.

    현재 임시 정책:

    manage_channels = True
    manage_messages = False

    manage_channels 유지 여부는
    팀 회의에서 최종 결정 예정.
    """

    category = guild.get_channel(
        category_id
    )


    if category is None:

        print(
            f"카테고리를 찾을 수 없음: "
            f"{category_id}"
        )

        return False


    try:

        host = (
            await guild.fetch_member(
                host_id
            )
        )


    except discord.NotFound:

        print(
            f"모임장을 찾을 수 없음: "
            f"{host_id}"
        )

        return False


    except discord.Forbidden:

        print(
            f"모임장 조회 권한 없음: "
            f"{host_id}"
        )

        return False


    host_overwrite = (
        discord.PermissionOverwrite(

            view_channel=True,

            read_message_history=True,

            send_messages=True,

            connect=True,

            speak=True,

            # 현재 임시 HOST 정책
            manage_channels=True,

            # 팀 회의 전까지 미적용
            # manage_messages=True,
        )
    )


    # 카테고리
    await category.set_permissions(

        host,

        overwrite=host_overwrite,
    )


    # 하위 채널
    for channel in category.channels:

        await channel.set_permissions(

            host,

            overwrite=host_overwrite,
        )


    print(
        f"HOST 권한 부여 완료: "
        f"{host} "
        f"→ {category.name}"
    )


    return True


# =========================================================
# 10. Discord 모임 공간 삭제
# =========================================================

async def delete_meeting_space(
    guild: discord.Guild,
    category_id: int,
) -> bool:
    """
    모임 종료 시 Discord 공간 전체 삭제.

    Discord 카테고리 50개 제한을 고려하여
    종료된 모임 공간은 보관하지 않는다.

    순서:

    1. 하위 채널 삭제
    2. 카테고리 삭제
    """

    category = guild.get_channel(
        category_id
    )


    if category is None:

        print(
            f"카테고리를 찾을 수 없음 "
            f"또는 이미 삭제됨: "
            f"{category_id}"
        )

        return False


    print(
        f"\n모임 Discord 공간 삭제 시작: "
        f"{category.name}"
    )


    # -----------------------------------------------------
    # 10-1. 하위 채널 삭제
    # -----------------------------------------------------

    for channel in list(
        category.channels
    ):

        try:

            channel_name = (
                channel.name
            )

            channel_id = (
                channel.id
            )


            await channel.delete(
                reason="PlayMate 모임 종료"
            )


            print(
                f"채널 삭제 완료: "
                f"{channel_name} "
                f"(ID: {channel_id})"
            )


        except discord.Forbidden:

            print(
                f"채널 삭제 권한 없음: "
                f"{channel.name}"
            )

            return False


        except discord.HTTPException as e:

            print(
                f"채널 삭제 실패: "
                f"{channel.name} / "
                f"{e}"
            )

            return False


    # -----------------------------------------------------
    # 10-2. 카테고리 삭제
    # -----------------------------------------------------

    try:

        category_name = (
            category.name
        )

        category_id_value = (
            category.id
        )


        await category.delete(
            reason="PlayMate 모임 종료"
        )


        print(
            f"카테고리 삭제 완료: "
            f"{category_name} "
            f"(ID: {category_id_value})"
        )


        return True


    except discord.Forbidden:

        print(
            f"카테고리 삭제 권한 없음: "
            f"{category.name}"
        )

        return False


    except discord.HTTPException as e:

        print(
            f"카테고리 삭제 실패: "
            f"{category.name} / "
            f"{e}"
        )

        return False


# =========================================================
# 11. 일회성 모임 삭제 예정시각 계산
# =========================================================

def get_one_time_scheduled_delete_at(
    end_at: datetime,
) -> datetime:
    """
    일회성 모임은 end_at 이후
    24시간 뒤 Discord 공간을 삭제한다.
    """

    return (
        end_at
        + timedelta(
            hours=ONE_TIME_DELETE_GRACE_HOURS
        )
    )


# =========================================================
# 12. Discord 메시지 활동 감지
#
# 상시모임 채널에서 사용자가 메시지를 작성하면
#
# last_activity_at 갱신
#
# 비활성 경고 또는 삭제 예약이 존재하면
# 활동 재개로 판단해 취소.
#
# 중요:
# 메시지 본문은 DB에 저장하지 않는다.
# =========================================================

@client.event
async def on_message(
    message: discord.Message,
):

    # Bot 메시지는 사용자 활동으로 보지 않는다.
    if message.author.bot:
        return


    # DM 무시
    if message.guild is None:
        return


    # 카테고리가 없는 일반 채널 무시
    if message.channel.category is None:
        return


    category_id = (
        message.channel.category.id
    )


    # 현재 테스트 데이터에 없는 모임은 무시
    #
    # 실제 서비스에서는
    # category_id → recruit 조회로 교체 예정.
    if (
        category_id
        not in TEST_ONGOING_MEETINGS
    ):
        return


    meeting = (
        TEST_ONGOING_MEETINGS[
            category_id
        ]
    )


    # 이미 삭제된 모임은 무시
    if (
        meeting.get(
            "discord_deleted_at"
        )
        is not None
    ):
        return


    now = datetime.now(KST)


    recruit_id = (
        meeting[
            "recruit_id"
        ]
    )


    # -----------------------------------------------------
    # 마지막 활동 시각 갱신
    # -----------------------------------------------------

    meeting[
        "last_activity_at"
    ] = now


    # -----------------------------------------------------
    # 비활성 경고/삭제 예약이 있었다면
    # 활동 재개로 판단
    # -----------------------------------------------------

    if (
        meeting.get(
            "inactivity_warned_at"
        )
        is not None

        or

        meeting.get(
            "scheduled_delete_at"
        )
        is not None
    ):

        meeting[
            "inactivity_warned_at"
        ] = None


        meeting[
            "scheduled_delete_at"
        ] = None


        print(
            f"\n[상시모임 활동 재개]\n"
            f"recruit_id="
            f"{recruit_id}\n"
            f"자동 종료 예약 취소"
        )


    print(
        f"\n[상시모임 활동 감지]\n"
        f"recruit_id="
        f"{recruit_id}\n"
        f"category_id="
        f"{category_id}\n"
        f"last_activity_at="
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )


    # 실제 서비스에서는 여기서:
    #
    # UPDATE recruit_discord_channels
    # SET
    #     last_activity_at = now,
    #     inactivity_warned_at = NULL,
    #     scheduled_delete_at = NULL
    # WHERE recruit_id = ...


# =========================================================
# 13. 모임 라이프사이클 검사
#
# 테스트:
# 1분마다
#
# 실서비스:
# 하루 1회
#
# 여기서 일회성 + 상시모임을 함께 검사한다.
# =========================================================

@tasks.loop(
    seconds=CHECK_INTERVAL_SECONDS
)
async def check_meeting_lifecycle():

    now = datetime.now(KST)


    print(
        f"\n[모임 라이프사이클 검사] "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )


    guild = client.get_guild(
        GUILD_ID
    )


    if guild is None:

        print(
            "Discord 서버를 "
            "찾을 수 없습니다."
        )

        return


    # =====================================================
    # 13-1. 일회성 모임 검사
    # =====================================================

    for meeting in (
        TEST_ONE_TIME_MEETINGS
    ):

        recruit_id = (
            meeting[
                "recruit_id"
            ]
        )

        category_id = (
            meeting[
                "category_id"
            ]
        )

        end_at = (
            meeting[
                "end_at"
            ]
        )

        discord_deleted_at = (
            meeting.get(
                "discord_deleted_at"
            )
        )


        # 이미 삭제 완료
        if discord_deleted_at is not None:
            continue


        scheduled_delete_at = (
            get_one_time_scheduled_delete_at(
                end_at
            )
        )


        print(
            f"[일회성 모임] "
            f"recruit_id="
            f"{recruit_id} | "
            f"삭제예정="
            f"{scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )


        # 아직 삭제 시간 전
        if now < scheduled_delete_at:
            continue


        print(
            f"[일회성 모임 자동 종료 대상] "
            f"recruit_id="
            f"{recruit_id}"
        )


        deleted = (
            await delete_meeting_space(

                guild=guild,

                category_id=category_id,
            )
        )


        if deleted:

            meeting[
                "discord_deleted_at"
            ] = now


            print(
                f"[일회성 모임 자동 종료 성공] "
                f"recruit_id="
                f"{recruit_id}"
            )


            # 실제 서비스:
            #
            # recruits.status = CLOSED
            #
            # recruit_discord_channels
            # .discord_deleted_at = now


    # =====================================================
    # 13-2. 상시모임 검사
    # =====================================================

    for (
        category_id,
        meeting
    ) in list(
        TEST_ONGOING_MEETINGS.items()
    ):


        recruit_id = (
            meeting[
                "recruit_id"
            ]
        )


        host_id = (
            meeting[
                "host_id"
            ]
        )


        last_activity_at = (
            meeting.get(
                "last_activity_at"
            )
        )


        inactivity_warned_at = (
            meeting.get(
                "inactivity_warned_at"
            )
        )


        scheduled_delete_at = (
            meeting.get(
                "scheduled_delete_at"
            )
        )


        discord_deleted_at = (
            meeting.get(
                "discord_deleted_at"
            )
        )


        # -------------------------------------------------
        # 이미 삭제 완료
        # -------------------------------------------------

        if discord_deleted_at is not None:

            continue


        # =================================================
        # 삭제 예약이 존재하는 경우
        # =================================================

        if scheduled_delete_at is not None:


            print(
                f"[상시모임] "
                f"recruit_id="
                f"{recruit_id} | "
                f"삭제예정="
                f"{scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )


            # 아직 7일 유예기간
            if now < scheduled_delete_at:

                continue


            # -------------------------------------------------
            # 중요 안전장치
            #
            # 정상 흐름에서는 on_message()에서
            # scheduled_delete_at을 None으로 바꾼다.
            #
            # 하지만 DB 반영 지연 / 프로세스 경쟁 /
            # 상태 불일치 등이 생겼을 가능성에 대비해
            #
            # 삭제 직전 최신 활동을 한 번 더 확인한다.
            #
            # 경고 후 새 활동이 있었다면 삭제 금지.
            # -------------------------------------------------

            if (
                inactivity_warned_at
                is not None

                and

                last_activity_at
                is not None

                and

                last_activity_at
                > inactivity_warned_at
            ):

                print(
                    f"경고 이후 활동 발견: "
                    f"recruit_id="
                    f"{recruit_id}"
                )


                meeting[
                    "inactivity_warned_at"
                ] = None


                meeting[
                    "scheduled_delete_at"
                ] = None


                print(
                    "→ 자동삭제 예약 취소"
                )


                continue


            # -------------------------------------------------
            # 유예기간 종료
            # -------------------------------------------------

            print(
                f"\n[상시모임 자동 종료 대상]\n"
                f"recruit_id="
                f"{recruit_id}"
            )


            deleted = (
                await delete_meeting_space(

                    guild=guild,

                    category_id=category_id,
                )
            )


            if deleted:

                meeting[
                    "discord_deleted_at"
                ] = now


                print(
                    f"\n[상시모임 자동 종료 성공]\n"
                    f"recruit_id="
                    f"{recruit_id}\n"
                    f"discord_deleted_at="
                    f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
                )


                # 실제 서비스:
                #
                # recruits.status = CLOSED
                #
                # recruit_discord_channels
                # .discord_deleted_at = now


            continue


        # =================================================
        # 삭제 예약이 없는 상시모임
        #
        # 30일 비활성 여부 확인
        # =================================================

        if last_activity_at is None:

            continue


        inactive_duration = (
            now
            - last_activity_at
        )


        print(
            f"[상시모임] "
            f"recruit_id="
            f"{recruit_id} | "
            f"비활성 기간="
            f"{inactive_duration.days}일"
        )


        # 아직 30일 미만
        if (
            inactive_duration
            < timedelta(
                days=INACTIVITY_DAYS
            )
        ):

            continue


        # 이미 경고를 보냄
        if inactivity_warned_at is not None:

            continue


        # =================================================
        # 30일 비활성
        #
        # HOST 경고 DM
        # =================================================

        try:

            host = (
                await guild.fetch_member(
                    host_id
                )
            )


            scheduled_delete_at = (
                now
                + timedelta(
                    days=
                    INACTIVITY_GRACE_DAYS
                )
            )


            await host.send(

                "PlayMate 모임 활동 안내\n\n"

                f"모임(recruit_id="
                f"{recruit_id})에서 "

                f"최근 "
                f"{INACTIVITY_DAYS}일 동안 "

                "Discord 활동이 "
                "확인되지 않았습니다.\n\n"

                f"앞으로 "
                f"{INACTIVITY_GRACE_DAYS}일 동안 "

                "활동이 없으면 "
                "모임이 자동 종료되고 "

                "Discord 공간이 "
                "삭제됩니다.\n\n"

                "모임 채널에서 "
                "다시 활동이 발생하면 "

                "자동 종료 예약은 "
                "취소됩니다."
            )


            meeting[
                "inactivity_warned_at"
            ] = now


            meeting[
                "scheduled_delete_at"
            ] = (
                scheduled_delete_at
            )


            print(
                f"비활성 경고 DM 전송 완료: "
                f"recruit_id="
                f"{recruit_id}"
            )


            print(
                f"자동 삭제 예정: "
                f"{scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )


        except discord.NotFound:

            print(
                f"HOST를 찾을 수 없음: "
                f"host_id="
                f"{host_id}"
            )


        except discord.Forbidden:

            print(
                f"HOST에게 DM을 "
                f"보낼 수 없음: "
                f"recruit_id="
                f"{recruit_id}"
            )


        except discord.HTTPException as e:

            print(
                f"DM 전송 실패: "
                f"recruit_id="
                f"{recruit_id} / "
                f"{e}"
            )


# =========================================================
# 14. Discord 준비 전에 Task 시작 방지
# =========================================================

@check_meeting_lifecycle.before_loop
async def before_check_meeting_lifecycle():

    await client.wait_until_ready()


# =========================================================
# 15. Discord 로그인 완료
# =========================================================

@client.event
async def on_ready():

    print(
        f"\nBot 로그인 성공: "
        f"{client.user}"
    )


    guild = client.get_guild(
        GUILD_ID
    )


    if guild is None:

        print(
            "테스트 서버를 "
            "찾지 못했습니다."
        )

        return


    print(
        f"서버 연결 성공: "
        f"{guild.name}"
    )


    print(
        "PlayMate Discord Bot "
        "라이프사이클 관리 준비 완료"
    )


    # Discord 재연결 시
    # on_ready()가 여러 번 실행될 수 있으므로
    # Task 중복 실행 방지

    if not (
        check_meeting_lifecycle
        .is_running()
    ):

        check_meeting_lifecycle.start()


        if TEST_MODE:

            print(
                "모임 라이프사이클 검사 시작 "
                "(테스트: 1분 주기)"
            )

        else:

            print(
                "모임 라이프사이클 검사 시작 "
                "(실서비스: 하루 1회)"
            )


# =========================================================
# 16. Bot 실행
# =========================================================

client.run(TOKEN)