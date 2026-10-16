# import os

# import discord
# from dotenv import load_dotenv


# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)


# intents = discord.Intents.default()

# client = discord.Client(intents=intents)


# @client.event
# async def on_ready():
#     print(f"Bot 로그인 성공: {client.user}")

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾지 못했습니다.")
#         return

#     print(f"서버 연결 성공: {guild.name}")


# client.run(TOKEN)

# -----------------------------------------------------

# import os

# import discord
# from dotenv import load_dotenv


# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)


# intents = discord.Intents.default()

# client = discord.Client(intents=intents)


# async def get_or_create_meeting_category(guild: discord.Guild):
#     category_name = "모임"

#     # 이미 '모임' 카테고리가 있는지 찾기
#     category = discord.utils.get(
#         guild.categories,
#         name=category_name
#     )

#     if category:
#         print(f"기존 카테고리 사용: {category.name}")
#         return category

#     # 없으면 새로 생성
#     category = await guild.create_category(category_name)

#     print(f"카테고리 생성 완료: {category.name}")

#     return category


# async def create_meeting_channels(
#     guild: discord.Guild,
#     meeting_name: str,
# ):
#     category = await get_or_create_meeting_category(guild)

#     text_channel = await guild.create_text_channel(
#         name=meeting_name,
#         category=category,
#         topic=f"{meeting_name} 모임 채팅방"
#     )

#     voice_channel = await guild.create_voice_channel(
#         name=meeting_name,
#         category=category
#     )

#     print(f"텍스트 채널 생성: {text_channel.name}")
#     print(f"음성 채널 생성: {voice_channel.name}")


# @client.event
# async def on_ready():
#     print(f"Bot 로그인 성공: {client.user}")

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾지 못했습니다.")
#         return

#     print(f"서버 연결 성공: {guild.name}")

#     # 테스트용 모임 생성
#     await create_meeting_channels(
#         guild=guild,
#         meeting_name="알고리즘-스터디"
#     )


# client.run(TOKEN)

# ----------------------------------
# import os
# import re

# import discord
# from dotenv import load_dotenv


# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)


# intents = discord.Intents.default()
# client = discord.Client(intents=intents)


# def normalize_channel_name(name: str) -> str:
#     """
#     모임명을 Discord 텍스트 채널명으로 사용하기 쉽게 변환.
#     지금은 테스트용.
#     """

#     name = name.strip().lower()

#     # 공백 / 언더스코어 → -
#     name = re.sub(r"[\s_]+", "-", name)

#     # 한글, 영문, 숫자, - 외의 문자 제거
#     name = re.sub(r"[^가-힣a-z0-9-]", "", name)

#     # --- 같이 여러 개 생긴 경우 하나로
#     name = re.sub(r"-+", "-", name)

#     # 앞뒤 - 제거
#     name = name.strip("-")

#     # 혹시 전부 제거된 경우
#     if not name:
#         name = "meeting"

#     return name


# async def get_or_create_meeting_category(guild: discord.Guild):
#     category_name = "모임"

#     category = discord.utils.get(
#         guild.categories,
#         name=category_name
#     )

#     if category:
#         print(f"기존 카테고리 사용: {category.name}")
#         return category

#     category = await guild.create_category(category_name)

#     print(f"카테고리 생성 완료: {category.name}")

#     return category


# async def create_meeting_channels(
#     guild: discord.Guild,
#     meeting_name: str,
#     visibility: str,
#     participant_ids: list[int] | None = None,
# ):
#     participant_ids = participant_ids or []

#     category = await get_or_create_meeting_category(guild)
#     channel_name = normalize_channel_name(meeting_name)

#     visibility = visibility.upper()

#     if visibility not in ("PUBLIC", "PRIVATE"):
#         raise ValueError("visibility은 PUBLIC 또는 PRIVATE여야 합니다.")

#     # -------------------------
#     # 기본 권한
#     # -------------------------

#     if visibility == "PUBLIC":
#         text_overwrites = {
#             guild.default_role: discord.PermissionOverwrite(
#                 view_channel=True,
#                 read_message_history=True,
#                 send_messages=False,
#             )
#         }

#         voice_overwrites = {
#             guild.default_role: discord.PermissionOverwrite(
#                 view_channel=True,
#                 connect=False,
#                 speak=False,
#             )
#         }

#     else:  # PRIVATE
#         text_overwrites = {
#             guild.default_role: discord.PermissionOverwrite(
#                 view_channel=False,
#             )
#         }

#         voice_overwrites = {
#             guild.default_role: discord.PermissionOverwrite(
#                 view_channel=False,
#                 connect=False,
#             )
#         }

#     # -------------------------
#     # 참여자 권한 추가
#     # -------------------------

#     for participant_id in participant_ids:
#         try:
#             member = await guild.fetch_member(participant_id)

#         except discord.NotFound:
#             print(f"참여자를 찾을 수 없음: {participant_id}")
#             continue

#         except discord.Forbidden:
#             print(f"참여자 조회 권한 없음: {participant_id}")
#             continue

#         text_overwrites[member] = discord.PermissionOverwrite(
#             view_channel=True,
#             read_message_history=True,
#             send_messages=True,
#         )

#         voice_overwrites[member] = discord.PermissionOverwrite(
#             view_channel=True,
#             connect=True,
#             speak=True,
#         )

#     # -------------------------
#     # 텍스트 채널
#     # -------------------------

#     text_channel = discord.utils.get(
#         category.text_channels,
#         name=channel_name
#     )

#     if text_channel:
#         print(f"기존 텍스트 채널 사용: {text_channel.name}")

#         # 기존 채널에도 새 권한 적용
#         await text_channel.edit(
#             overwrites=text_overwrites,
#             topic=f"[{visibility}] {meeting_name} 모임 채팅방"
#         )

#     else:
#         text_channel = await guild.create_text_channel(
#             name=channel_name,
#             category=category,
#             topic=f"[{visibility}] {meeting_name} 모임 채팅방",
#             overwrites=text_overwrites,
#         )

#         print(f"텍스트 채널 생성 완료: {text_channel.name}")

#     # -------------------------
#     # 음성 채널
#     # -------------------------

#     voice_channel = discord.utils.get(
#         category.voice_channels,
#         name=channel_name
#     )

#     if voice_channel:
#         print(f"기존 음성 채널 사용: {voice_channel.name}")

#         await voice_channel.edit(
#             overwrites=voice_overwrites
#         )

#     else:
#         voice_channel = await guild.create_voice_channel(
#             name=channel_name,
#             category=category,
#             overwrites=voice_overwrites,
#         )

#         print(f"음성 채널 생성 완료: {voice_channel.name}")

#     return text_channel, voice_channel


# @client.event
# async def on_ready():
#     print(f"\nBot 로그인 성공: {client.user}")

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾지 못했습니다.")
#         return

#     print(f"서버 연결 성공: {guild.name}")

#     # PUBLIC 모임 테스트
#     await create_meeting_channels(
#         guild=guild,
#         meeting_name="PUBLIC 테스트",
#         visibility="PUBLIC",
#         participant_ids=[]
#     )

#     # PRIVATE 모임 테스트
#     await create_meeting_channels(
#         guild=guild,
#         meeting_name="PRIVATE 테스트",
#         visibility="PRIVATE",
#         participant_ids=[]
#     )


# client.run(TOKEN)

# ---------------------------------------------------
# import os

# import discord
# from dotenv import load_dotenv


# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)


# intents = discord.Intents.default()
# client = discord.Client(intents=intents)


# async def create_meeting_space(
#     guild: discord.Guild,
#     meeting_name: str,
#     visibility: str = "PUBLIC",
#     participant_ids: list[int] | None = None,
#     create_voice_channel: bool = True,
# ):
#     """
#     PlayMate에서 생성 승인된 모임을 Discord 공간으로 생성.

#     중요한 원칙:
#     - 모임명 중복 검사는 PlayMate 백엔드/DB에서 처리
#     - Bot은 meeting_name을 임의로 정규화해서
#       기존 모임과 같은지 판단하지 않음
#     - 현재 테스트 단계에서는 호출될 때마다 새 공간 생성
#     - 실제 서비스에서는 recruit_id 기준으로 중복 생성을 막을 예정
#     """

#     participant_ids = participant_ids or []

#     visibility = visibility.upper()

#     if visibility not in ("PUBLIC", "PRIVATE"):
#         raise ValueError(
#             "visibility은 PUBLIC 또는 PRIVATE여야 합니다."
#         )

#     # -------------------------
#     # 1. 기본 권한 설정
#     # -------------------------

#     if visibility == "PUBLIC":
#         # 비참여자:
#         # 카테고리/채널은 보이지만
#         # 텍스트 작성 X, 음성 접속 X
#         overwrites = {
#             guild.default_role: discord.PermissionOverwrite(
#                 view_channel=True,
#                 read_message_history=True,
#                 send_messages=False,
#                 connect=False,
#                 speak=False,
#             )
#         }

#     else:
#         # PRIVATE:
#         # 비참여자는 카테고리 자체가 안 보이게
#         overwrites = {
#             guild.default_role: discord.PermissionOverwrite(
#                 view_channel=False,
#                 read_message_history=False,
#                 send_messages=False,
#                 connect=False,
#                 speak=False,
#             )
#         }

#     # -------------------------
#     # 2. 참여자 권한 추가
#     # -------------------------

#     for participant_id in participant_ids:
#         try:
#             member = await guild.fetch_member(participant_id)

#         except discord.NotFound:
#             print(
#                 f"참여자를 찾을 수 없음: {participant_id}"
#             )
#             continue

#         except discord.Forbidden:
#             print(
#                 f"참여자 조회 권한 없음: {participant_id}"
#             )
#             continue

#         overwrites[member] = discord.PermissionOverwrite(
#             view_channel=True,
#             read_message_history=True,
#             send_messages=True,
#             connect=True,
#             speak=True,
#         )

#     # -------------------------
#     # 3. 모임 전용 카테고리 생성
#     # -------------------------

#     category = await guild.create_category(
#         name=meeting_name,
#         overwrites=overwrites,
#     )

#     print(
#         f"모임 카테고리 생성 완료: "
#         f"{category.name} "
#         f"(ID: {category.id})"
#     )

#     # -------------------------
#     # 4. 텍스트 채널 생성
#     # -------------------------

#     text_channel = await guild.create_text_channel(
#         name="채팅",
#         category=category,
#         topic=f"[{visibility}] {meeting_name}",
#     )

#     print(
#         f"텍스트 채널 생성 완료: "
#         f"{text_channel.name} "
#         f"(ID: {text_channel.id})"
#     )

#     # -------------------------
#     # 5. 음성 채널 생성
#     # -------------------------

#     voice_channel = None

#     if create_voice_channel:
#         voice_channel = await guild.create_voice_channel(
#         name="음성",
#         category=category,
#         )   

#         print(
#             f"음성 채널 생성 완료: "
#             f"{voice_channel.name} "
#             f"(ID: {voice_channel.id})"
#         )

#     else:
#         print("음성 채널 생성 안 함")

#     return category, text_channel, voice_channel


# @client.event
# async def on_ready():
#     print(f"\nBot 로그인 성공: {client.user}")

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾지 못했습니다.")
#         return

#     print(f"서버 연결 성공: {guild.name}")

#     # -------------------------
#     # 테스트용 모임
#     # -------------------------

#     await create_meeting_space(
#         guild=guild,
#         meeting_name="알고리즘 스터디",
#         visibility="PUBLIC",
#         participant_ids=[],
#         create_voice_channel=True,
#     )


# client.run(TOKEN)

# ------------------------------------------
# 참가 권한 다시 뺏기

# import os

# import discord
# from dotenv import load_dotenv


# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)

# TEST_PARTICIPANT_ID = 1483439065641783449
# TEST_HOST_ID = 1483439065641783449

# PUBLIC_CATEGORY_ID = 1558443184034422814
# PRIVATE_CATEGORY_ID = 1558443189726216205

# intents = discord.Intents.default()
# client = discord.Client(intents=intents)

# # 지금 단계에선 새로 만들지 않을거니까 일단 주석
# # async def create_meeting_space(
# #     guild: discord.Guild,
# #     meeting_name: str,
# #     visibility: str = "PUBLIC",
# #     participant_ids: list[int] | None = None,
# #     create_voice_channel: bool = True,
# # ):
# #     """
# #     PlayMate에서 생성 승인된 모임을 Discord 공간으로 생성.

# #     중요한 원칙:
# #     - 모임명 중복 검사는 PlayMate 백엔드/DB에서 처리
# #     - Bot은 meeting_name을 임의로 정규화해서
# #       기존 모임과 같은지 판단하지 않음
# #     - 현재 테스트 단계에서는 호출될 때마다 새 공간 생성
# #     - 실제 서비스에서는 recruit_id 기준으로 중복 생성을 막을 예정
# #     """

# #     participant_ids = participant_ids or []

# #     visibility = visibility.upper()

# #     if visibility not in ("PUBLIC", "PRIVATE"):
# #         raise ValueError(
# #             "visibility은 PUBLIC 또는 PRIVATE여야 합니다."
# #         )

# #     # -------------------------
# #     # 1. 기본 권한 설정
# #     # -------------------------

# #     if visibility == "PUBLIC":
# #         # 비참여자:
# #         # 카테고리/채널은 보이지만
# #         # 텍스트 작성 X, 음성 접속 X
# #         overwrites = {
# #             guild.default_role: discord.PermissionOverwrite(
# #                 view_channel=True,
# #                 read_message_history=True,
# #                 send_messages=False,
# #                 connect=False,
# #                 speak=False,
# #             )
# #         }

# #     else:
# #         # PRIVATE:
# #         # 비참여자는 카테고리 자체가 안 보이게
# #         overwrites = {
# #             guild.default_role: discord.PermissionOverwrite(
# #                 view_channel=False,
# #                 read_message_history=False,
# #                 send_messages=False,
# #                 connect=False,
# #                 speak=False,
# #             )
# #         }

# #     # -------------------------
# #     # 2. 참여자 권한 추가
# #     # -------------------------

# #     for participant_id in participant_ids:
# #         try:
# #             member = await guild.fetch_member(participant_id)

# #         except discord.NotFound:
# #             print(
# #                 f"참여자를 찾을 수 없음: {participant_id}"
# #             )
# #             continue

# #         except discord.Forbidden:
# #             print(
# #                 f"참여자 조회 권한 없음: {participant_id}"
# #             )
# #             continue

# #         overwrites[member] = discord.PermissionOverwrite(
# #             view_channel=True,
# #             read_message_history=True,
# #             send_messages=True,
# #             connect=True,
# #             speak=True,
# #         )

# #     # -------------------------
# #     # 3. 모임 전용 카테고리 생성
# #     # -------------------------

# #     category = await guild.create_category(
# #         name=meeting_name,
# #         overwrites=overwrites,
# #     )

# #     print(
# #         f"모임 카테고리 생성 완료: "
# #         f"{category.name} "
# #         f"(ID: {category.id})"
# #     )

# #     # -------------------------
# #     # 4. 텍스트 채널 생성
# #     # -------------------------

# #     text_channel = await guild.create_text_channel(
# #         name="채팅",
# #         category=category,
# #         topic=f"[{visibility}] {meeting_name}",
# #     )

# #     print(
# #         f"텍스트 채널 생성 완료: "
# #         f"{text_channel.name} "
# #         f"(ID: {text_channel.id})"
# #     )

# #     # -------------------------
# #     # 5. 음성 채널 생성
# #     # -------------------------

# #     voice_channel = None

# #     if create_voice_channel:
# #         voice_channel = await guild.create_voice_channel(
# #         name="음성",
# #         category=category,
# #         )   

# #         print(
# #             f"음성 채널 생성 완료: "
# #             f"{voice_channel.name} "
# #             f"(ID: {voice_channel.id})"
# #         )

# #     else:
# #         print("음성 채널 생성 안 함")

# #     return category, text_channel, voice_channel

# async def remove_participant_permissions(
#     guild: discord.Guild,
#     category_id: int,
#     participant_id: int,
#     visibility: str,
# ):
#     visibility = visibility.upper()

#     if visibility not in ("PUBLIC", "PRIVATE"):
#         raise ValueError("visibility은 PUBLIC 또는 PRIVATE여야 합니다.")

#     category = guild.get_channel(category_id)

#     if category is None:
#         print(f"카테고리를 찾을 수 없음: {category_id}")
#         return

#     try:
#         member = await guild.fetch_member(participant_id)

#     except discord.NotFound:
#         print(f"참여자를 찾을 수 없음: {participant_id}")
#         return

#     except discord.Forbidden:
#         print(f"참여자 조회 권한 없음: {participant_id}")
#         return

#     if visibility == "PUBLIC":
#         overwrite = discord.PermissionOverwrite(
#             view_channel=True,
#             read_message_history=True,
#             send_messages=False,
#             connect=False,
#             speak=False,
#         )

#         await category.set_permissions(
#             member,
#             overwrite=overwrite
#         )

#         for channel in category.channels:
#             await channel.set_permissions(
#                 member,
#                 overwrite=overwrite
#             )

#         print(
#             f"PUBLIC 참여 취소 처리 완료: "
#             f"{member} → 읽기만 허용"
#         )

#     else:
#         await category.set_permissions(
#             member,
#             overwrite=None
#         )

#         for channel in category.channels:
#             await channel.set_permissions(
#                 member,
#                 overwrite=None
#             )

#         print(
#             f"PRIVATE 참여 취소 처리 완료: "
#             f"{member} → 접근 권한 제거"
#         )

# async def grant_host_permissions(
#     guild: discord.Guild,
#     category_id: int,
#     host_id: int,
# ):
#     category = guild.get_channel(category_id)

#     if category is None:
#         print(f"카테고리를 찾을 수 없음: {category_id}")
#         return

#     try:
#         host = await guild.fetch_member(host_id)

#     except discord.NotFound:
#         print(f"모임장을 찾을 수 없음: {host_id}")
#         return

#     except discord.Forbidden:
#         print(f"모임장 조회 권한 없음: {host_id}")
#         return

#     host_overwrite = discord.PermissionOverwrite(
#         view_channel=True,
#         read_message_history=True,
#         send_messages=True,
#         connect=True,
#         speak=True,

#         # HOST 전용 관리 권한
#         manage_channels=True,
#         manage_messages=True,
#     )

#     # 카테고리
#     await category.set_permissions(
#         host,
#         overwrite=host_overwrite,
#     )

#     # 카테고리 안 채널
#     for channel in category.channels:
#         await channel.set_permissions(
#             host,
#             overwrite=host_overwrite,
#         )

#     print(
#         f"HOST 권한 부여 완료: "
#         f"{host} → {category.name}"
#     )


# @client.event
# async def on_ready():
#     print(f"\nBot 로그인 성공: {client.user}")

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾지 못했습니다.")
#         return

#     print(f"서버 연결 성공: {guild.name}")

#     await remove_participant_permissions(
#         guild=guild,
#         category_id=PUBLIC_CATEGORY_ID,
#         participant_id=TEST_PARTICIPANT_ID,
#         visibility="PUBLIC",
#     )

#     await remove_participant_permissions(
#         guild=guild,
#         category_id=PRIVATE_CATEGORY_ID,
#         participant_id=TEST_PARTICIPANT_ID,
#         visibility="PRIVATE",
#     )


# client.run(TOKEN)

#-------------------------------------------------------
# import os

# import discord
# from dotenv import load_dotenv


# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)

# TEST_PARTICIPANT_ID = 1483439065641783449
# TEST_HOST_ID = 1483439065641783449

# PUBLIC_CATEGORY_ID = 1558443184034422814
# PRIVATE_CATEGORY_ID = 1558443189726216205

# intents = discord.Intents.default()
# client = discord.Client(intents=intents)

# # 지금 단계에선 새로 만들지 않을거니까 일단 주석
# # async def create_meeting_space(
# #     guild: discord.Guild,
# #     meeting_name: str,
# #     visibility: str = "PUBLIC",
# #     participant_ids: list[int] | None = None,
# #     create_voice_channel: bool = True,
# # ):
# #     """
# #     PlayMate에서 생성 승인된 모임을 Discord 공간으로 생성.

# #     중요한 원칙:
# #     - 모임명 중복 검사는 PlayMate 백엔드/DB에서 처리
# #     - Bot은 meeting_name을 임의로 정규화해서
# #       기존 모임과 같은지 판단하지 않음
# #     - 현재 테스트 단계에서는 호출될 때마다 새 공간 생성
# #     - 실제 서비스에서는 recruit_id 기준으로 중복 생성을 막을 예정
# #     """

# #     participant_ids = participant_ids or []

# #     visibility = visibility.upper()

# #     if visibility not in ("PUBLIC", "PRIVATE"):
# #         raise ValueError(
# #             "visibility은 PUBLIC 또는 PRIVATE여야 합니다."
# #         )

# #     # -------------------------
# #     # 1. 기본 권한 설정
# #     # -------------------------

# #     if visibility == "PUBLIC":
# #         # 비참여자:
# #         # 카테고리/채널은 보이지만
# #         # 텍스트 작성 X, 음성 접속 X
# #         overwrites = {
# #             guild.default_role: discord.PermissionOverwrite(
# #                 view_channel=True,
# #                 read_message_history=True,
# #                 send_messages=False,
# #                 connect=False,
# #                 speak=False,
# #             )
# #         }

# #     else:
# #         # PRIVATE:
# #         # 비참여자는 카테고리 자체가 안 보이게
# #         overwrites = {
# #             guild.default_role: discord.PermissionOverwrite(
# #                 view_channel=False,
# #                 read_message_history=False,
# #                 send_messages=False,
# #                 connect=False,
# #                 speak=False,
# #             )
# #         }

# #     # -------------------------
# #     # 2. 참여자 권한 추가
# #     # -------------------------

# #     for participant_id in participant_ids:
# #         try:
# #             member = await guild.fetch_member(participant_id)

# #         except discord.NotFound:
# #             print(
# #                 f"참여자를 찾을 수 없음: {participant_id}"
# #             )
# #             continue

# #         except discord.Forbidden:
# #             print(
# #                 f"참여자 조회 권한 없음: {participant_id}"
# #             )
# #             continue

# #         overwrites[member] = discord.PermissionOverwrite(
# #             view_channel=True,
# #             read_message_history=True,
# #             send_messages=True,
# #             connect=True,
# #             speak=True,
# #         )

# #     # -------------------------
# #     # 3. 모임 전용 카테고리 생성
# #     # -------------------------

# #     category = await guild.create_category(
# #         name=meeting_name,
# #         overwrites=overwrites,
# #     )

# #     print(
# #         f"모임 카테고리 생성 완료: "
# #         f"{category.name} "
# #         f"(ID: {category.id})"
# #     )

# #     # -------------------------
# #     # 4. 텍스트 채널 생성
# #     # -------------------------

# #     text_channel = await guild.create_text_channel(
# #         name="채팅",
# #         category=category,
# #         topic=f"[{visibility}] {meeting_name}",
# #     )

# #     print(
# #         f"텍스트 채널 생성 완료: "
# #         f"{text_channel.name} "
# #         f"(ID: {text_channel.id})"
# #     )

# #     # -------------------------
# #     # 5. 음성 채널 생성
# #     # -------------------------

# #     voice_channel = None

# #     if create_voice_channel:
# #         voice_channel = await guild.create_voice_channel(
# #         name="음성",
# #         category=category,
# #         )   

# #         print(
# #             f"음성 채널 생성 완료: "
# #             f"{voice_channel.name} "
# #             f"(ID: {voice_channel.id})"
# #         )

# #     else:
# #         print("음성 채널 생성 안 함")

# #     return category, text_channel, voice_channel

# # 이번엔 필요없으니까 일단 주석처리
# # async def remove_participant_permissions(
# #     guild: discord.Guild,
# #     category_id: int,
# #     participant_id: int,
# #     visibility: str,
# # ):
# #     visibility = visibility.upper()

# #     if visibility not in ("PUBLIC", "PRIVATE"):
# #         raise ValueError("visibility은 PUBLIC 또는 PRIVATE여야 합니다.")

# #     category = guild.get_channel(category_id)

# #     if category is None:
# #         print(f"카테고리를 찾을 수 없음: {category_id}")
# #         return

# #     try:
# #         member = await guild.fetch_member(participant_id)

# #     except discord.NotFound:
# #         print(f"참여자를 찾을 수 없음: {participant_id}")
# #         return

# #     except discord.Forbidden:
# #         print(f"참여자 조회 권한 없음: {participant_id}")
# #         return

# #     if visibility == "PUBLIC":
# #         overwrite = discord.PermissionOverwrite(
# #             view_channel=True,
# #             read_message_history=True,
# #             send_messages=False,
# #             connect=False,
# #             speak=False,
# #         )

# #         await category.set_permissions(
# #             member,
# #             overwrite=overwrite
# #         )

# #         for channel in category.channels:
# #             await channel.set_permissions(
# #                 member,
# #                 overwrite=overwrite
# #             )

# #         print(
# #             f"PUBLIC 참여 취소 처리 완료: "
# #             f"{member} → 읽기만 허용"
# #         )

# #     else:
# #         await category.set_permissions(
# #             member,
# #             overwrite=None
# #         )

# #         for channel in category.channels:
# #             await channel.set_permissions(
# #                 member,
# #                 overwrite=None
# #             )

# #         print(
# #             f"PRIVATE 참여 취소 처리 완료: "
# #             f"{member} → 접근 권한 제거"
# #         )

# async def grant_host_permissions(
#     guild: discord.Guild,
#     category_id: int,
#     host_id: int,
# ):
#     category = guild.get_channel(category_id)

#     if category is None:
#         print(f"카테고리를 찾을 수 없음: {category_id}")
#         return

#     try:
#         host = await guild.fetch_member(host_id)

#     except discord.NotFound:
#         print(f"모임장을 찾을 수 없음: {host_id}")
#         return

#     except discord.Forbidden:
#         print(f"모임장 조회 권한 없음: {host_id}")
#         return

#     host_overwrite = discord.PermissionOverwrite(
#         view_channel=True,
#         read_message_history=True,
#         send_messages=True,
#         connect=True,
#         speak=True,

#         # 일단 테스트/임시 정책
#         manage_channels=True,

#         # 회의 전까지는 제외
#         # manage_messages=True,
#     )

#     # 카테고리
#     await category.set_permissions(
#         host,
#         overwrite=host_overwrite,
#     )

#     # 카테고리 안 채널
#     for channel in category.channels:
#         await channel.set_permissions(
#             host,
#             overwrite=host_overwrite,
#         )

#     print(
#         f"HOST 권한 부여 완료: "
#         f"{host} → {category.name}"
#     )


# @client.event
# async def on_ready():
#     print(f"\nBot 로그인 성공: {client.user}")

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾지 못했습니다.")
#         return

#     print(f"서버 연결 성공: {guild.name}")

#     await grant_host_permissions(
#         guild=guild,
#         category_id=PUBLIC_CATEGORY_ID,
#         host_id=TEST_HOST_ID,
#     )

#     await grant_host_permissions(
#         guild=guild,
#         category_id=PRIVATE_CATEGORY_ID,
#         host_id=TEST_HOST_ID,
#     )


# client.run(TOKEN)

# ------------------------------------------------
# import os

# import discord
# from dotenv import load_dotenv


# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)

# TEST_PARTICIPANT_ID = 1483439065641783449
# TEST_HOST_ID = 1483439065641783449

# PUBLIC_CATEGORY_ID = 1558443184034422814
# PRIVATE_CATEGORY_ID = 1558443189726216205

# intents = discord.Intents.default()
# client = discord.Client(intents=intents)

# # 지금 단계에선 새로 만들지 않을거니까 일단 주석
# # async def create_meeting_space(
# #     guild: discord.Guild,
# #     meeting_name: str,
# #     visibility: str = "PUBLIC",
# #     participant_ids: list[int] | None = None,
# #     create_voice_channel: bool = True,
# # ):
# #     """
# #     PlayMate에서 생성 승인된 모임을 Discord 공간으로 생성.

# #     중요한 원칙:
# #     - 모임명 중복 검사는 PlayMate 백엔드/DB에서 처리
# #     - Bot은 meeting_name을 임의로 정규화해서
# #       기존 모임과 같은지 판단하지 않음
# #     - 현재 테스트 단계에서는 호출될 때마다 새 공간 생성
# #     - 실제 서비스에서는 recruit_id 기준으로 중복 생성을 막을 예정
# #     """

# #     participant_ids = participant_ids or []

# #     visibility = visibility.upper()

# #     if visibility not in ("PUBLIC", "PRIVATE"):
# #         raise ValueError(
# #             "visibility은 PUBLIC 또는 PRIVATE여야 합니다."
# #         )

# #     # -------------------------
# #     # 1. 기본 권한 설정
# #     # -------------------------

# #     if visibility == "PUBLIC":
# #         # 비참여자:
# #         # 카테고리/채널은 보이지만
# #         # 텍스트 작성 X, 음성 접속 X
# #         overwrites = {
# #             guild.default_role: discord.PermissionOverwrite(
# #                 view_channel=True,
# #                 read_message_history=True,
# #                 send_messages=False,
# #                 connect=False,
# #                 speak=False,
# #             )
# #         }

# #     else:
# #         # PRIVATE:
# #         # 비참여자는 카테고리 자체가 안 보이게
# #         overwrites = {
# #             guild.default_role: discord.PermissionOverwrite(
# #                 view_channel=False,
# #                 read_message_history=False,
# #                 send_messages=False,
# #                 connect=False,
# #                 speak=False,
# #             )
# #         }

# #     # -------------------------
# #     # 2. 참여자 권한 추가
# #     # -------------------------

# #     for participant_id in participant_ids:
# #         try:
# #             member = await guild.fetch_member(participant_id)

# #         except discord.NotFound:
# #             print(
# #                 f"참여자를 찾을 수 없음: {participant_id}"
# #             )
# #             continue

# #         except discord.Forbidden:
# #             print(
# #                 f"참여자 조회 권한 없음: {participant_id}"
# #             )
# #             continue

# #         overwrites[member] = discord.PermissionOverwrite(
# #             view_channel=True,
# #             read_message_history=True,
# #             send_messages=True,
# #             connect=True,
# #             speak=True,
# #         )

# #     # -------------------------
# #     # 3. 모임 전용 카테고리 생성
# #     # -------------------------

# #     category = await guild.create_category(
# #         name=meeting_name,
# #         overwrites=overwrites,
# #     )

# #     print(
# #         f"모임 카테고리 생성 완료: "
# #         f"{category.name} "
# #         f"(ID: {category.id})"
# #     )

# #     # -------------------------
# #     # 4. 텍스트 채널 생성
# #     # -------------------------

# #     text_channel = await guild.create_text_channel(
# #         name="채팅",
# #         category=category,
# #         topic=f"[{visibility}] {meeting_name}",
# #     )

# #     print(
# #         f"텍스트 채널 생성 완료: "
# #         f"{text_channel.name} "
# #         f"(ID: {text_channel.id})"
# #     )

# #     # -------------------------
# #     # 5. 음성 채널 생성
# #     # -------------------------

# #     voice_channel = None

# #     if create_voice_channel:
# #         voice_channel = await guild.create_voice_channel(
# #         name="음성",
# #         category=category,
# #         )   

# #         print(
# #             f"음성 채널 생성 완료: "
# #             f"{voice_channel.name} "
# #             f"(ID: {voice_channel.id})"
# #         )

# #     else:
# #         print("음성 채널 생성 안 함")

# #     return category, text_channel, voice_channel

# # 이번엔 필요없으니까 일단 주석처리
# # async def remove_participant_permissions(
# #     guild: discord.Guild,
# #     category_id: int,
# #     participant_id: int,
# #     visibility: str,
# # ):
# #     visibility = visibility.upper()

# #     if visibility not in ("PUBLIC", "PRIVATE"):
# #         raise ValueError("visibility은 PUBLIC 또는 PRIVATE여야 합니다.")

# #     category = guild.get_channel(category_id)

# #     if category is None:
# #         print(f"카테고리를 찾을 수 없음: {category_id}")
# #         return

# #     try:
# #         member = await guild.fetch_member(participant_id)

# #     except discord.NotFound:
# #         print(f"참여자를 찾을 수 없음: {participant_id}")
# #         return

# #     except discord.Forbidden:
# #         print(f"참여자 조회 권한 없음: {participant_id}")
# #         return

# #     if visibility == "PUBLIC":
# #         overwrite = discord.PermissionOverwrite(
# #             view_channel=True,
# #             read_message_history=True,
# #             send_messages=False,
# #             connect=False,
# #             speak=False,
# #         )

# #         await category.set_permissions(
# #             member,
# #             overwrite=overwrite
# #         )

# #         for channel in category.channels:
# #             await channel.set_permissions(
# #                 member,
# #                 overwrite=overwrite
# #             )

# #         print(
# #             f"PUBLIC 참여 취소 처리 완료: "
# #             f"{member} → 읽기만 허용"
# #         )

# #     else:
# #         await category.set_permissions(
# #             member,
# #             overwrite=None
# #         )

# #         for channel in category.channels:
# #             await channel.set_permissions(
# #                 member,
# #                 overwrite=None
# #             )

# #         print(
# #             f"PRIVATE 참여 취소 처리 완료: "
# #             f"{member} → 접근 권한 제거"
# #         )

# # 이번 섹션은 모임종료이므로 잠시 주석처리
# # async def grant_host_permissions(
# #     guild: discord.Guild,
# #     category_id: int,
# #     host_id: int,
# # ):
# #     category = guild.get_channel(category_id)

# #     if category is None:
# #         print(f"카테고리를 찾을 수 없음: {category_id}")
# #         return

# #     try:
# #         host = await guild.fetch_member(host_id)

# #     except discord.NotFound:
# #         print(f"모임장을 찾을 수 없음: {host_id}")
# #         return

# #     except discord.Forbidden:
# #         print(f"모임장 조회 권한 없음: {host_id}")
# #         return

# #     host_overwrite = discord.PermissionOverwrite(
# #         view_channel=True,
# #         read_message_history=True,
# #         send_messages=True,
# #         connect=True,
# #         speak=True,

# #         # 일단 테스트/임시 정책
# #         manage_channels=True,

# #         # 회의 전까지는 제외
# #         # manage_messages=True,
# #     )

# #     # 카테고리
# #     await category.set_permissions(
# #         host,
# #         overwrite=host_overwrite,
# #     )

# #     # 카테고리 안 채널
# #     for channel in category.channels:
# #         await channel.set_permissions(
# #             host,
# #             overwrite=host_overwrite,
# #         )

# #     print(
# #         f"HOST 권한 부여 완료: "
# #         f"{host} → {category.name}"
# #     )

# async def delete_meeting_space(
#     guild: discord.Guild,
#     category_id: int,
# ):
#     category = guild.get_channel(category_id)

#     if category is None:
#         print(f"카테고리를 찾을 수 없음: {category_id}")
#         return

#     print(f"모임 Discord 공간 삭제 시작: {category.name}")

#     # 1. 카테고리 안의 채널 먼저 삭제
#     for channel in list(category.channels):
#         try:
#             await channel.delete(
#                 reason="PlayMate 모임 종료"
#             )

#             print(
#                 f"채널 삭제 완료: "
#                 f"{channel.name} "
#                 f"(ID: {channel.id})"
#             )

#         except discord.Forbidden:
#             print(
#                 f"채널 삭제 권한 없음: "
#                 f"{channel.name}"
#             )

#         except discord.HTTPException as e:
#             print(
#                 f"채널 삭제 실패: "
#                 f"{channel.name} / {e}"
#             )

#     # 2. 카테고리 삭제
#     try:
#         await category.delete(
#             reason="PlayMate 모임 종료"
#         )

#         print(
#             f"카테고리 삭제 완료: "
#             f"{category.name} "
#             f"(ID: {category.id})"
#         )

#     except discord.Forbidden:
#         print(
#             f"카테고리 삭제 권한 없음: "
#             f"{category.name}"
#         )

#     except discord.HTTPException as e:
#         print(
#             f"카테고리 삭제 실패: "
#             f"{category.name} / {e}"
#         )

# @client.event
# async def on_ready():
#     print(f"\nBot 로그인 성공: {client.user}")

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾지 못했습니다.")
#         return

#     print(f"서버 연결 성공: {guild.name}")

#     await delete_meeting_space(
#         guild=guild,
#         category_id=PUBLIC_CATEGORY_ID,
#     )

#     await delete_meeting_space(
#         guild=guild,
#         category_id=PRIVATE_CATEGORY_ID,
#     )


# client.run(TOKEN)

#-------------------------------------------------------------
# import os
# from datetime import datetime, timedelta
# from zoneinfo import ZoneInfo

# import discord
# from discord.ext import tasks
# from dotenv import load_dotenv


# # =========================================================
# # 1. 환경변수 / 기본 설정
# # =========================================================

# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")

# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)

# KST = ZoneInfo("Asia/Seoul")



# # =========================================================
# # 2. Discord Client
# # =========================================================

# intents = discord.Intents.default()
# client = discord.Client(intents=intents)


# # =========================================================
# # 3. 현재 테스트용 데이터
# #
# # 주의:
# # 실제 서비스에서는 이 값들을 코드에 직접 넣지 않고
# # PostgreSQL DB에서 조회할 예정
# # =========================================================

# TEST_CATEGORY_ID = 1558418888583151666
# # ↑ 새로 만든 "일회성 자동삭제 테스트" 카테고리 ID로 변경


# TEST_MEETINGS = [
#     {
#         "recruit_id": 1,
#         "category_id": TEST_CATEGORY_ID,

#         # 테스트용:
#         # 모임이 25시간 전에 종료됐다고 가정
#         #
#         # 삭제 기준은 end_at + 24시간이므로
#         # Bot 실행 시 이미 자동 삭제 대상이 됨
#         "end_at": datetime.now(KST) - timedelta(hours=25),
#     }
# ]


# # =========================================================
# # 4. 삭제 예정 시각 계산
# # =========================================================

# def get_scheduled_delete_at(end_at: datetime) -> datetime:
#     """
#     일회성 모임은 종료 시각으로부터
#     24시간 후 Discord 공간을 삭제한다.
#     """

#     return end_at + timedelta(hours=24)


# # =========================================================
# # 5. Discord 모임 공간 삭제
# # =========================================================

# async def delete_meeting_space(
#     guild: discord.Guild,
#     category_id: int,
# ) -> bool:
#     """
#     모임 종료 시 Discord 공간 전체 삭제.

#     순서:
#     1. 카테고리 안의 채널 삭제
#     2. 카테고리 삭제

#     성공하면 True,
#     실패하면 False 반환.
#     """

#     category = guild.get_channel(category_id)

#     if category is None:
#         print(
#             f"카테고리를 찾을 수 없음 또는 이미 삭제됨: "
#             f"{category_id}"
#         )
#         return False

#     print(
#         f"\n모임 Discord 공간 삭제 시작: "
#         f"{category.name}"
#     )

#     # -----------------------------------------------------
#     # 1. 카테고리 내부 채널 삭제
#     # -----------------------------------------------------

#     for channel in list(category.channels):

#         try:
#             channel_name = channel.name
#             channel_id = channel.id

#             await channel.delete(
#                 reason="PlayMate 모임 종료"
#             )

#             print(
#                 f"채널 삭제 완료: "
#                 f"{channel_name} "
#                 f"(ID: {channel_id})"
#             )

#         except discord.Forbidden:
#             print(
#                 f"채널 삭제 권한 없음: "
#                 f"{channel.name}"
#             )
#             return False

#         except discord.HTTPException as e:
#             print(
#                 f"채널 삭제 실패: "
#                 f"{channel.name} / {e}"
#             )
#             return False

#     # -----------------------------------------------------
#     # 2. 카테고리 삭제
#     # -----------------------------------------------------

#     try:
#         category_name = category.name
#         category_id_value = category.id

#         await category.delete(
#             reason="PlayMate 모임 종료"
#         )

#         print(
#             f"카테고리 삭제 완료: "
#             f"{category_name} "
#             f"(ID: {category_id_value})"
#         )

#         return True

#     except discord.Forbidden:
#         print(
#             f"카테고리 삭제 권한 없음: "
#             f"{category.name}"
#         )
#         return False

#     except discord.HTTPException as e:
#         print(
#             f"카테고리 삭제 실패: "
#             f"{category.name} / {e}"
#         )
#         return False


# # =========================================================
# # 6. 종료된 일회성 모임 주기 검사
# # =========================================================

# @tasks.loop(minutes=1)
# async def check_finished_meetings():

#     now = datetime.now(KST)

#     print(
#         f"\n[자동 종료 검사] "
#         f"현재 시각: {now.strftime('%Y-%m-%d %H:%M:%S')}"
#     )

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾을 수 없습니다.")
#         return

#     for meeting in TEST_MEETINGS:

#         recruit_id = meeting["recruit_id"]
#         category_id = meeting["category_id"]
#         end_at = meeting["end_at"]

#         scheduled_delete_at = get_scheduled_delete_at(
#             end_at
#         )

#         print(
#             f"recruit_id={recruit_id} | "
#             f"종료={end_at.strftime('%Y-%m-%d %H:%M:%S')} | "
#             f"삭제예정="
#             f"{scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}"
#         )

#         # 아직 삭제 예정 시간이 되지 않았으면 넘어감
#         if now < scheduled_delete_at:

#             print(
#                 f"아직 삭제 대상 아님: "
#                 f"recruit_id={recruit_id}"
#             )

#             continue

#         # -------------------------------------------------
#         # 이미 삭제되었는지 확인
#         # -------------------------------------------------

#         category = guild.get_channel(category_id)

#         if category is None:

#             print(
#                 f"이미 삭제된 모임 공간: "
#                 f"recruit_id={recruit_id}"
#             )

#             continue

#         # -------------------------------------------------
#         # 자동 삭제 실행
#         # -------------------------------------------------

#         print(
#             f"자동 종료 대상 발견: "
#             f"recruit_id={recruit_id}"
#         )

#         deleted = await delete_meeting_space(
#             guild=guild,
#             category_id=category_id,
#         )

#         if deleted:

#             print(
#                 f"자동 종료 처리 성공: "
#                 f"recruit_id={recruit_id}"
#             )

#             # 실제 서비스에서는 여기서:
#             #
#             # recruits 상태 → CLOSED
#             # recruit_discord_channels.discord_deleted_at
#             # → 현재 시각 기록
#             #
#             # 을 DB에 반영할 예정


# # =========================================================
# # 7. Bot 준비 완료 전에는 task 실행하지 않도록 대기
# # =========================================================

# @check_finished_meetings.before_loop
# async def before_check_finished_meetings():
#     await client.wait_until_ready()


# # =========================================================
# # 8. Discord Bot 로그인
# # =========================================================

# @client.event
# async def on_ready():

#     print(f"\nBot 로그인 성공: {client.user}")

#     guild = client.get_guild(GUILD_ID)

#     if guild is None:
#         print("테스트 서버를 찾지 못했습니다.")
#         return

#     print(f"서버 연결 성공: {guild.name}")

#     # on_ready()는 재연결 시 여러 번 실행될 수 있으므로
#     # task 중복 실행 방지
#     if not check_finished_meetings.is_running():

#         check_finished_meetings.start()

#         print("일회성 모임 자동 종료 검사 시작")


# # =========================================================
# # 9. Bot 실행
# # =========================================================

# client.run(TOKEN)

#--------------------------------------------------------------------------
# import os
# from datetime import datetime, timedelta
# from zoneinfo import ZoneInfo

# import discord
# from discord.ext import tasks
# from dotenv import load_dotenv


# # =========================================================
# # 1. 환경변수 / 기본 설정
# # =========================================================

# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")

# if not TOKEN:
#     raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")

# if not GUILD_ID:
#     raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")

# GUILD_ID = int(GUILD_ID)

# # 한국 시간
# KST = ZoneInfo("Asia/Seoul")


# # =========================================================
# # 2. Discord Client
# # =========================================================

# intents = discord.Intents.default()

# client = discord.Client(
#     intents=intents
# )


# # =========================================================
# # 3. 상시모임 활동 감지 테스트 데이터
# #
# # 실제 서비스에서는 이 데이터가 코드에 직접 들어가지 않고
# # PostgreSQL DB에서 조회될 예정
# #
# # key:
# #   Discord 카테고리 ID
# #
# # value:
# #   PlayMate 모임 정보
# # =========================================================

# TEST_ONGOING_MEETINGS = {
#     1558476831563194448: {       # ← 실제 테스트 카테고리 ID로 변경
#         "recruit_id": 2,
#         "last_activity_at": None,
#     }
# }


# # =========================================================
# # 4. Discord 모임 공간 삭제 함수
# #
# # 이전 단계에서 검증 완료한 함수.
# #
# # 지금 상시모임 활동 감지 테스트에서는 직접 호출하지 않지만
# # 이후 비활성 모임 자동삭제에서도 다시 사용할 예정이므로
# # 함수 자체는 남겨둔다.
# # =========================================================

# async def delete_meeting_space(
#     guild: discord.Guild,
#     category_id: int,
# ) -> bool:

#     category = guild.get_channel(category_id)

#     if category is None:
#         print(
#             f"카테고리를 찾을 수 없음 또는 이미 삭제됨: "
#             f"{category_id}"
#         )
#         return False

#     print(
#         f"\n모임 Discord 공간 삭제 시작: "
#         f"{category.name}"
#     )

#     # -----------------------------------------------------
#     # 카테고리 내부 채널 먼저 삭제
#     # -----------------------------------------------------

#     for channel in list(category.channels):

#         try:
#             channel_name = channel.name
#             channel_id = channel.id

#             await channel.delete(
#                 reason="PlayMate 모임 종료"
#             )

#             print(
#                 f"채널 삭제 완료: "
#                 f"{channel_name} "
#                 f"(ID: {channel_id})"
#             )

#         except discord.Forbidden:

#             print(
#                 f"채널 삭제 권한 없음: "
#                 f"{channel.name}"
#             )

#             return False

#         except discord.HTTPException as e:

#             print(
#                 f"채널 삭제 실패: "
#                 f"{channel.name} / {e}"
#             )

#             return False

#     # -----------------------------------------------------
#     # 카테고리 삭제
#     # -----------------------------------------------------

#     try:
#         category_name = category.name
#         category_id_value = category.id

#         await category.delete(
#             reason="PlayMate 모임 종료"
#         )

#         print(
#             f"카테고리 삭제 완료: "
#             f"{category_name} "
#             f"(ID: {category_id_value})"
#         )

#         return True

#     except discord.Forbidden:

#         print(
#             f"카테고리 삭제 권한 없음: "
#             f"{category.name}"
#         )

#         return False

#     except discord.HTTPException as e:

#         print(
#             f"카테고리 삭제 실패: "
#             f"{category.name} / {e}"
#         )

#         return False


# # =========================================================
# # 5. 일회성 모임 자동 종료
# #
# # 이전 단계에서
# # end_at + 24시간 자동 삭제까지 검증 완료.
# #
# # 현재는 "상시모임 활동 감지"만 테스트할 것이므로
# # 일단 실행하지 않는다.
# #
# # 실제 서비스에서는 다시 활성화해서
# # 상시모임 관리 로직과 함께 사용하게 된다.
# # =========================================================


# # def get_scheduled_delete_at(
# #     end_at: datetime
# # ) -> datetime:
# #
# #     return end_at + timedelta(hours=24)


# # @tasks.loop(minutes=1)
# # async def check_finished_meetings():
# #
# #     ...
# #
# #     이전에 테스트했던
# #     end_at + 24시간 검사 코드
# #     ...


# # @check_finished_meetings.before_loop
# # async def before_check_finished_meetings():
# #
# #     await client.wait_until_ready()


# # =========================================================
# # 6. 상시모임 Discord 활동 감지
# #
# # 모임 카테고리 안에서 사용자가 메시지를 작성하면
# # 해당 모임의 last_activity_at을 현재 시각으로 갱신한다.
# #
# # 중요:
# # 메시지 본문은 저장하지 않는다.
# # "마지막 활동 시각"만 기록한다.
# # =========================================================

# @client.event
# async def on_message(
#     message: discord.Message
# ):

#     # -----------------------------------------------------
#     # 1. Bot 자신이 작성한 메시지는 무시
#     #
#     # Bot 메시지까지 활동으로 판단하면
#     # 자동 알림 때문에 모임이 계속 ACTIVE가 되는 문제가 생길 수 있음
#     # -----------------------------------------------------

#     if message.author.bot:
#         return


#     # -----------------------------------------------------
#     # 2. DM에서 발생한 메시지는 무시
#     #
#     # 우리는 PlayMate 모임 Discord 채널의 활동만 감지한다.
#     # -----------------------------------------------------

#     if message.guild is None:
#         return


#     # -----------------------------------------------------
#     # 3. 카테고리가 없는 채널은 무시
#     #
#     # PlayMate 모임은
#     # "모임 하나 = 카테고리 하나"
#     # 구조이므로 카테고리 ID를 기준으로 모임을 찾는다.
#     # -----------------------------------------------------

#     if message.channel.category is None:
#         return


#     category_id = message.channel.category.id


#     # -----------------------------------------------------
#     # 4. PlayMate 상시모임이 아니면 무시
#     #
#     # 테스트 단계에서는 TEST_ONGOING_MEETINGS에
#     # 등록되어 있는 카테고리만 추적한다.
#     #
#     # 실제 서비스에서는 DB의
#     # recruit_discord_channels와 연결할 예정.
#     # -----------------------------------------------------

#     if category_id not in TEST_ONGOING_MEETINGS:
#         return


#     # -----------------------------------------------------
#     # 5. 마지막 활동 시간 갱신
#     # -----------------------------------------------------

#     now = datetime.now(KST)

#     TEST_ONGOING_MEETINGS[
#         category_id
#     ]["last_activity_at"] = now


#     recruit_id = TEST_ONGOING_MEETINGS[
#         category_id
#     ]["recruit_id"]


#     # -----------------------------------------------------
#     # 6. 테스트용 로그 출력
#     #
#     # 실제 서비스에서는 여기서
#     # DB의 last_activity_at을 UPDATE하게 된다.
#     # -----------------------------------------------------

#     print(
#         f"\n[상시모임 활동 감지]\n"
#         f"recruit_id={recruit_id}\n"
#         f"category_id={category_id}\n"
#         f"last_activity_at="
#         f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
#     )


# # =========================================================
# # 7. Discord Bot 로그인 완료
# # =========================================================

# @client.event
# async def on_ready():

#     print(
#         f"\nBot 로그인 성공: "
#         f"{client.user}"
#     )

#     guild = client.get_guild(
#         GUILD_ID
#     )

#     if guild is None:

#         print(
#             "테스트 서버를 찾지 못했습니다."
#         )

#         return

#     print(
#         f"서버 연결 성공: "
#         f"{guild.name}"
#     )


#     # -----------------------------------------------------
#     # 이전 단계:
#     # 일회성 모임 자동 종료 검사
#     #
#     # 현재 테스트에서는 실행하지 않음.
#     #
#     # 나중에는 다시 아래처럼 활성화:
#     #
#     # if not check_finished_meetings.is_running():
#     #     check_finished_meetings.start()
#     #
#     # -----------------------------------------------------

#     print(
#         "상시모임 활동 감지 준비 완료"
#     )


# # =========================================================
# # 8. Bot 실행
# # =========================================================

# client.run(TOKEN)

#------------------------------------------------------------------------
# import os
# from datetime import datetime, timedelta
# from zoneinfo import ZoneInfo

# import discord
# from discord.ext import tasks
# from dotenv import load_dotenv


# # =========================================================
# # 1. 환경변수 / 기본 설정
# # =========================================================

# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError(
#         "DISCORD_BOT_TOKEN이 .env에 없습니다."
#     )

# if not GUILD_ID:
#     raise ValueError(
#         "DISCORD_GUILD_ID가 .env에 없습니다."
#     )


# GUILD_ID = int(GUILD_ID)

# # 한국 시간
# KST = ZoneInfo("Asia/Seoul")


# # =========================================================
# # 2. 상시모임 비활성 정책
# #
# # 실제 서비스에서는 운영 정책에 따라
# # 설정값 또는 DB/환경설정으로 관리하는 것이 좋음.
# # =========================================================

# INACTIVITY_DAYS = 30
# INACTIVITY_GRACE_DAYS = 7


# # =========================================================
# # 3. Discord Client
# # =========================================================

# intents = discord.Intents.default()

# client = discord.Client(
#     intents=intents
# )


# # =========================================================
# # 4. 테스트용 상시모임 데이터
# #
# # 실제 서비스에서는 PostgreSQL DB에서 조회할 예정.
# #
# # key:
# #   Discord 모임 카테고리 ID
# #
# # value:
# #   PlayMate 모임 정보
# #
# # 현재 테스트 목적:
# # - 마지막 활동이 31일 전이었다고 가정
# # - Bot 실행 후 30일 비활성으로 판단
# # - HOST에게 DM 전송
# # - 7일 후 삭제 예정 시각 생성
# # =========================================================

# TEST_ONGOING_MEETINGS = {

#     # ↓ 여기에 실제 "상시모임 테스트" 카테고리 ID 입력
#     1558476831563194448: {

#         "recruit_id": 2,

#         # 테스트용 HOST Discord 사용자 ID
#         "host_id": 1483439065641783449,

#         # 31일 전에 마지막 활동했다고 가정
#         "last_activity_at":
#             datetime.now(KST)
#             - timedelta(days=31),

#         # 아직 비활성 경고를 보내지 않음
#         "inactivity_warned_at": None,

#         # 아직 자동 삭제 예약 없음
#         "scheduled_delete_at": None,
#     }
# }


# # =========================================================
# # 5. Discord 모임 공간 삭제 함수
# #
# # 이전 테스트에서 이미 검증한 함수.
# #
# # 이번 단계에서는 실제 삭제하지 않지만
# # 다음 단계인 "7일 후 자동삭제"에서 다시 사용할 것이므로
# # 미리 그대로 남겨둔다.
# # =========================================================

# async def delete_meeting_space(
#     guild: discord.Guild,
#     category_id: int,
# ) -> bool:

#     category = guild.get_channel(
#         category_id
#     )

#     if category is None:

#         print(
#             f"카테고리를 찾을 수 없음 "
#             f"또는 이미 삭제됨: "
#             f"{category_id}"
#         )

#         return False


#     print(
#         f"\n모임 Discord 공간 삭제 시작: "
#         f"{category.name}"
#     )


#     # -----------------------------------------------------
#     # 1. 카테고리 내부 채널 삭제
#     # -----------------------------------------------------

#     for channel in list(
#         category.channels
#     ):

#         try:

#             channel_name = (
#                 channel.name
#             )

#             channel_id = (
#                 channel.id
#             )

#             await channel.delete(
#                 reason="PlayMate 모임 종료"
#             )

#             print(
#                 f"채널 삭제 완료: "
#                 f"{channel_name} "
#                 f"(ID: {channel_id})"
#             )


#         except discord.Forbidden:

#             print(
#                 f"채널 삭제 권한 없음: "
#                 f"{channel.name}"
#             )

#             return False


#         except discord.HTTPException as e:

#             print(
#                 f"채널 삭제 실패: "
#                 f"{channel.name} / {e}"
#             )

#             return False


#     # -----------------------------------------------------
#     # 2. 카테고리 삭제
#     # -----------------------------------------------------

#     try:

#         category_name = (
#             category.name
#         )

#         category_id_value = (
#             category.id
#         )

#         await category.delete(
#             reason="PlayMate 모임 종료"
#         )

#         print(
#             f"카테고리 삭제 완료: "
#             f"{category_name} "
#             f"(ID: {category_id_value})"
#         )

#         return True


#     except discord.Forbidden:

#         print(
#             f"카테고리 삭제 권한 없음: "
#             f"{category.name}"
#         )

#         return False


#     except discord.HTTPException as e:

#         print(
#             f"카테고리 삭제 실패: "
#             f"{category.name} / {e}"
#         )

#         return False


# # =========================================================
# # 6. 상시모임 메시지 활동 감지
# #
# # 사용자가 PlayMate 모임 카테고리 안에서
# # 메시지를 작성하면
# #
# # last_activity_at = 현재 시각
# #
# # 으로 갱신한다.
# #
# # 중요:
# # 메시지 내용 자체는 저장하지 않는다.
# # =========================================================

# @client.event
# async def on_message(
#     message: discord.Message
# ):

#     # -----------------------------------------------------
#     # 1. Bot 메시지는 활동으로 판단하지 않음
#     #
#     # Bot이 알림 메시지를 보낸 것이
#     # 사용자 활동으로 처리되면
#     # 비활성 모임이 계속 ACTIVE가 될 수 있기 때문.
#     # -----------------------------------------------------

#     if message.author.bot:
#         return


#     # -----------------------------------------------------
#     # 2. DM 메시지는 무시
#     #
#     # PlayMate 모임 Discord 공간의 활동만 추적한다.
#     # -----------------------------------------------------

#     if message.guild is None:
#         return


#     # -----------------------------------------------------
#     # 3. 카테고리가 없는 채널은 무시
#     #
#     # PlayMate 구조:
#     #
#     # 모임 하나
#     # = Discord 카테고리 하나
#     # -----------------------------------------------------

#     if message.channel.category is None:
#         return


#     category_id = (
#         message.channel.category.id
#     )


#     # -----------------------------------------------------
#     # 4. 테스트 대상 모임인지 확인
#     #
#     # 현재는 TEST_ONGOING_MEETINGS에 등록된
#     # 카테고리만 추적.
#     #
#     # 실제 서비스에서는 DB 조회로 변경 예정.
#     # -----------------------------------------------------

#     if (
#         category_id
#         not in TEST_ONGOING_MEETINGS
#     ):
#         return


#     meeting = (
#         TEST_ONGOING_MEETINGS[
#             category_id
#         ]
#     )


#     # -----------------------------------------------------
#     # 5. 마지막 활동 시각 갱신
#     # -----------------------------------------------------

#     now = datetime.now(KST)

#     meeting[
#         "last_activity_at"
#     ] = now


#     recruit_id = (
#         meeting[
#             "recruit_id"
#         ]
#     )


#     # -----------------------------------------------------
#     # 6. 이전에 비활성 경고를 받은 상태라면
#     #    활동 재개로 판단
#     #
#     # 다음 단계에서 자동삭제 예약 취소 기능을
#     # 본격적으로 검증할 예정.
#     #
#     # 현재도 미리 상태를 초기화하도록 구현.
#     # -----------------------------------------------------

#     if (
#         meeting[
#             "inactivity_warned_at"
#         ]
#         is not None
#         or
#         meeting[
#             "scheduled_delete_at"
#         ]
#         is not None
#     ):

#         meeting[
#             "inactivity_warned_at"
#         ] = None

#         meeting[
#             "scheduled_delete_at"
#         ] = None

#         print(
#             f"\n[상시모임 활동 재개]\n"
#             f"recruit_id="
#             f"{recruit_id}\n"
#             f"자동 종료 예약 취소"
#         )


#     # -----------------------------------------------------
#     # 7. 활동 감지 로그
#     #
#     # 실제 서비스에서는 여기서
#     # DB의 last_activity_at을 UPDATE.
#     # -----------------------------------------------------

#     print(
#         f"\n[상시모임 활동 감지]\n"
#         f"recruit_id="
#         f"{recruit_id}\n"
#         f"category_id="
#         f"{category_id}\n"
#         f"last_activity_at="
#         f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
#     )


# # =========================================================
# # 7. 상시모임 비활성 검사
# #
# # 1분마다 테스트 데이터를 확인한다.
# #
# # 실제 서비스에서는
# # DB에서 last_activity_at 기준으로
# # 대상 모임을 조회하게 된다.
# # =========================================================

# @tasks.loop(minutes=1)
# async def check_inactive_ongoing_meetings():

#     now = datetime.now(KST)


#     print(
#         f"\n[상시모임 비활성 검사] "
#         f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
#     )


#     guild = client.get_guild(
#         GUILD_ID
#     )


#     if guild is None:

#         print(
#             "테스트 서버를 찾을 수 없습니다."
#         )

#         return


#     # -----------------------------------------------------
#     # 등록된 상시모임 순회
#     # -----------------------------------------------------

#     for (
#         category_id,
#         meeting
#     ) in TEST_ONGOING_MEETINGS.items():


#         recruit_id = (
#             meeting[
#                 "recruit_id"
#             ]
#         )


#         host_id = (
#             meeting[
#                 "host_id"
#             ]
#         )


#         last_activity_at = (
#             meeting[
#                 "last_activity_at"
#             ]
#         )


#         inactivity_warned_at = (
#             meeting[
#                 "inactivity_warned_at"
#             ]
#         )


#         # -------------------------------------------------
#         # 마지막 활동 시각이 없으면 검사 제외
#         # -------------------------------------------------

#         if last_activity_at is None:

#             print(
#                 f"last_activity_at 없음: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )

#             continue


#         # -------------------------------------------------
#         # 비활성 기간 계산
#         # -------------------------------------------------

#         inactive_duration = (
#             now
#             - last_activity_at
#         )


#         print(
#             f"recruit_id="
#             f"{recruit_id} | "
#             f"비활성 기간="
#             f"{inactive_duration.days}일"
#         )


#         # -------------------------------------------------
#         # 아직 30일 미만이면 정상 상태
#         # -------------------------------------------------

#         if (
#             inactive_duration
#             < timedelta(
#                 days=INACTIVITY_DAYS
#             )
#         ):

#             continue


#         # -------------------------------------------------
#         # 이미 경고를 보낸 상태면
#         # 같은 DM을 반복해서 보내지 않는다.
#         # -------------------------------------------------

#         if (
#             inactivity_warned_at
#             is not None
#         ):

#             print(
#                 f"이미 비활성 경고 전송됨: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )

#             continue


#         # -------------------------------------------------
#         # HOST에게 비활성 경고 DM 발송
#         # -------------------------------------------------

#         try:

#             host = (
#                 await guild.fetch_member(
#                     host_id
#                 )
#             )


#             # 7일 후 자동삭제 예정
#             scheduled_delete_at = (
#                 now
#                 + timedelta(
#                     days=
#                     INACTIVITY_GRACE_DAYS
#                 )
#             )


#             await host.send(
#                 "PlayMate 모임 활동 안내\n\n"

#                 f"모임(recruit_id="
#                 f"{recruit_id})에서 "

#                 f"최근 "
#                 f"{INACTIVITY_DAYS}일 동안 "

#                 "Discord 활동이 "
#                 "확인되지 않았습니다.\n\n"

#                 f"앞으로 "
#                 f"{INACTIVITY_GRACE_DAYS}일 동안 "

#                 "활동이 없으면 "
#                 "모임이 자동 종료되고 "

#                 "Discord 공간이 "
#                 "삭제됩니다.\n\n"

#                 "모임 채널에서 "
#                 "다시 활동이 발생하면 "

#                 "자동 종료 예약은 "
#                 "취소됩니다."
#             )


#             # ---------------------------------------------
#             # 경고 시각 기록
#             # ---------------------------------------------

#             meeting[
#                 "inactivity_warned_at"
#             ] = now


#             # ---------------------------------------------
#             # 자동삭제 예정 시각 기록
#             # ---------------------------------------------

#             meeting[
#                 "scheduled_delete_at"
#             ] = (
#                 scheduled_delete_at
#             )


#             print(
#                 f"비활성 경고 DM 전송 완료: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )


#             print(
#                 f"자동 삭제 예정: "
#                 f"{scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}"
#             )


#         except discord.NotFound:

#             print(
#                 f"HOST를 찾을 수 없음: "
#                 f"host_id="
#                 f"{host_id}"
#             )


#         except discord.Forbidden:

#             print(
#                 f"HOST에게 DM을 "
#                 f"보낼 수 없음: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )


#         except discord.HTTPException as e:

#             print(
#                 f"DM 전송 실패: "
#                 f"recruit_id="
#                 f"{recruit_id} / "
#                 f"{e}"
#             )


# # =========================================================
# # 8. Bot 준비 완료 전에 Task 실행 방지
# # =========================================================

# @check_inactive_ongoing_meetings.before_loop
# async def before_check_inactive_ongoing_meetings():

#     await client.wait_until_ready()


# # =========================================================
# # 9. Discord Bot 로그인 완료
# # =========================================================

# @client.event
# async def on_ready():

#     print(
#         f"\nBot 로그인 성공: "
#         f"{client.user}"
#     )


#     guild = client.get_guild(
#         GUILD_ID
#     )


#     if guild is None:

#         print(
#             "테스트 서버를 "
#             "찾지 못했습니다."
#         )

#         return


#     print(
#         f"서버 연결 성공: "
#         f"{guild.name}"
#     )


#     print(
#         "상시모임 활동 감지 "
#         "준비 완료"
#     )


#     # -----------------------------------------------------
#     # on_ready()는 Discord 재연결 때
#     # 여러 번 실행될 수 있음.
#     #
#     # 따라서 Task가 이미 실행 중인지 확인한 뒤 시작.
#     # -----------------------------------------------------

#     if not (
#         check_inactive_ongoing_meetings
#         .is_running()
#     ):

#         (
#             check_inactive_ongoing_meetings
#             .start()
#         )

#         print(
#             "상시모임 비활성 검사 시작"
#         )


# # =========================================================
# # 10. Bot 실행
# # =========================================================

# client.run(TOKEN)

#---------------------------------------------------------------------
# import os
# from datetime import datetime, timedelta
# from zoneinfo import ZoneInfo

# import discord
# from discord.ext import tasks
# from dotenv import load_dotenv


# # =========================================================
# # 1. 환경변수 / 기본 설정
# # =========================================================

# load_dotenv()

# TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# if not TOKEN:
#     raise ValueError(
#         "DISCORD_BOT_TOKEN이 .env에 없습니다."
#     )

# if not GUILD_ID:
#     raise ValueError(
#         "DISCORD_GUILD_ID가 .env에 없습니다."
#     )


# GUILD_ID = int(GUILD_ID)

# KST = ZoneInfo("Asia/Seoul")


# # =========================================================
# # 2. 상시모임 비활성 정책
# # =========================================================

# INACTIVITY_DAYS = 30
# INACTIVITY_GRACE_DAYS = 7


# # =========================================================
# # 3. 검사 주기
# #
# # 테스트:
# #   1분마다 검사
# #
# # 실서비스:
# #   하루 1회 검사
# #
# # 실제 배포할 때 TEST_MODE = False 로 변경
# # =========================================================

# TEST_MODE = True

# CHECK_INTERVAL_SECONDS = (
#     60
#     if TEST_MODE
#     else 60 * 60 * 24
# )


# # =========================================================
# # 4. Discord Client
# # =========================================================

# intents = discord.Intents.default()

# client = discord.Client(
#     intents=intents
# )


# =========================================================
# 5. 테스트용 상시모임 데이터
#
# 이번 테스트 목적:
#
# 이미
# - 38일 동안 활동 없음
# - 8일 전에 HOST 경고 완료
# - 삭제 예정시각도 이미 지남
#
# 상태를 강제로 만들어서
# 자동삭제가 실제 실행되는지 확인한다.
#
# 실제 서비스에서는 PostgreSQL DB에서 조회할 예정.
# =========================================================

# TEST_ONGOING_MEETINGS = {

#     # ↓ 새로 만든 테스트 카테고리 ID로 변경
#     1558523368481882233: {

#         "recruit_id": 2,

#         # 테스트 HOST ID
#         "host_id": 1483439065641783449,

#         # 마지막 활동 = 38일 전
#         "last_activity_at":
#             datetime.now(KST)
#             - timedelta(days=38),

#         # 비활성 경고 = 8일 전
#         "inactivity_warned_at":
#             datetime.now(KST)
#             - timedelta(days=8),

#         # 원래 삭제 예정 = 1일 전
#         # 즉 현재 시점에는 이미 삭제 대상
#         "scheduled_delete_at":
#             datetime.now(KST)
#             - timedelta(days=1),

#         # 아직 Discord 공간은 삭제되지 않음
#         "discord_deleted_at": None,
#     }
# }


# # =========================================================
# # 6. Discord 모임 공간 삭제
# #
# # 이전 단계에서 실제 동작 검증 완료.
# #
# # 하위 채널
# # → 카테고리
# #
# # 순서로 삭제한다.
# # =========================================================

# async def delete_meeting_space(
#     guild: discord.Guild,
#     category_id: int,
# ) -> bool:

#     category = guild.get_channel(
#         category_id
#     )


#     if category is None:

#         print(
#             f"카테고리를 찾을 수 없음 "
#             f"또는 이미 삭제됨: "
#             f"{category_id}"
#         )

#         return False


#     print(
#         f"\n모임 Discord 공간 삭제 시작: "
#         f"{category.name}"
#     )


#     # -----------------------------------------------------
#     # 1. 카테고리 내부 채널 삭제
#     # -----------------------------------------------------

#     for channel in list(
#         category.channels
#     ):

#         try:

#             channel_name = (
#                 channel.name
#             )

#             channel_id = (
#                 channel.id
#             )


#             await channel.delete(
#                 reason="PlayMate 상시모임 자동 종료"
#             )


#             print(
#                 f"채널 삭제 완료: "
#                 f"{channel_name} "
#                 f"(ID: {channel_id})"
#             )


#         except discord.Forbidden:

#             print(
#                 f"채널 삭제 권한 없음: "
#                 f"{channel.name}"
#             )

#             return False


#         except discord.HTTPException as e:

#             print(
#                 f"채널 삭제 실패: "
#                 f"{channel.name} / "
#                 f"{e}"
#             )

#             return False


#     # -----------------------------------------------------
#     # 2. 카테고리 삭제
#     # -----------------------------------------------------

#     try:

#         category_name = (
#             category.name
#         )

#         category_id_value = (
#             category.id
#         )


#         await category.delete(
#             reason="PlayMate 상시모임 자동 종료"
#         )


#         print(
#             f"카테고리 삭제 완료: "
#             f"{category_name} "
#             f"(ID: {category_id_value})"
#         )


#         return True


#     except discord.Forbidden:

#         print(
#             f"카테고리 삭제 권한 없음: "
#             f"{category.name}"
#         )

#         return False


#     except discord.HTTPException as e:

#         print(
#             f"카테고리 삭제 실패: "
#             f"{category.name} / "
#             f"{e}"
#         )

#         return False


# # =========================================================
# # 7. 상시모임 활동 감지
# #
# # Discord 모임 채널에서
# # 사용자가 메시지를 작성하면
# #
# # last_activity_at 갱신
# #
# # 기존 비활성 경고 / 삭제 예약이 있다면
# # 모두 취소한다.
# #
# # 메시지 내용 자체는 저장하지 않는다.
# # =========================================================

# @client.event
# async def on_message(
#     message: discord.Message
# ):

#     # Bot 메시지는 활동으로 판단하지 않음
#     if message.author.bot:
#         return


#     # DM 무시
#     if message.guild is None:
#         return


#     # 카테고리 없는 채널 무시
#     if message.channel.category is None:
#         return


#     category_id = (
#         message.channel.category.id
#     )


#     # PlayMate 상시모임이 아니면 무시
#     if (
#         category_id
#         not in TEST_ONGOING_MEETINGS
#     ):
#         return


#     meeting = (
#         TEST_ONGOING_MEETINGS[
#             category_id
#         ]
#     )


#     # 이미 삭제된 모임이면 활동 처리하지 않음
#     if (
#         meeting[
#             "discord_deleted_at"
#         ]
#         is not None
#     ):
#         return


#     recruit_id = (
#         meeting[
#             "recruit_id"
#         ]
#     )


#     now = datetime.now(KST)


#     # -----------------------------------------------------
#     # 마지막 활동 시각 갱신
#     # -----------------------------------------------------

#     meeting[
#         "last_activity_at"
#     ] = now


#     # -----------------------------------------------------
#     # 비활성 경고 또는 삭제 예약이 있었다면
#     # 활동 재개로 판단하여 취소
#     # -----------------------------------------------------

#     if (
#         meeting[
#             "inactivity_warned_at"
#         ]
#         is not None

#         or

#         meeting[
#             "scheduled_delete_at"
#         ]
#         is not None
#     ):

#         meeting[
#             "inactivity_warned_at"
#         ] = None

#         meeting[
#             "scheduled_delete_at"
#         ] = None


#         print(
#             f"\n[상시모임 활동 재개]\n"
#             f"recruit_id="
#             f"{recruit_id}\n"
#             f"자동 종료 예약 취소"
#         )


#     print(
#         f"\n[상시모임 활동 감지]\n"
#         f"recruit_id="
#         f"{recruit_id}\n"
#         f"category_id="
#         f"{category_id}\n"
#         f"last_activity_at="
#         f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
#     )


# # =========================================================
# # 8. 상시모임 비활성 / 자동삭제 검사
# #
# # 테스트:
# #   1분마다 실행
# #
# # 실서비스:
# #   하루 1회 실행
# #
# # 검사 순서:
# #
# # 1. 이미 삭제됐는지 확인
# # 2. 삭제 예정시각이 지났는지 확인
# # 3. 활동이 다시 발생했는지 안전하게 확인
# # 4. 삭제 실행
# # 5. 아니면 30일 비활성 여부 확인
# # 6. HOST 경고 및 +7일 삭제 예약
# # =========================================================

# @tasks.loop(
#     seconds=CHECK_INTERVAL_SECONDS
# )
# async def check_inactive_ongoing_meetings():

#     now = datetime.now(KST)


#     print(
#         f"\n[상시모임 상태 검사] "
#         f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
#     )


#     guild = client.get_guild(
#         GUILD_ID
#     )


#     if guild is None:

#         print(
#             "Discord 서버를 "
#             "찾을 수 없습니다."
#         )

#         return


#     # -----------------------------------------------------
#     # 등록된 상시모임 순회
#     # -----------------------------------------------------

#     for (
#         category_id,
#         meeting
#     ) in list(
#         TEST_ONGOING_MEETINGS.items()
#     ):


#         recruit_id = (
#             meeting[
#                 "recruit_id"
#             ]
#         )


#         host_id = (
#             meeting[
#                 "host_id"
#             ]
#         )


#         last_activity_at = (
#             meeting[
#                 "last_activity_at"
#             ]
#         )


#         inactivity_warned_at = (
#             meeting[
#                 "inactivity_warned_at"
#             ]
#         )


#         scheduled_delete_at = (
#             meeting[
#                 "scheduled_delete_at"
#             ]
#         )


#         discord_deleted_at = (
#             meeting[
#                 "discord_deleted_at"
#             ]
#         )


#         # -------------------------------------------------
#         # 1. 이미 삭제 완료된 모임
#         # -------------------------------------------------

#         if (
#             discord_deleted_at
#             is not None
#         ):

#             print(
#                 f"이미 삭제 처리된 모임: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )

#             continue


#         # =================================================
#         # 2. 자동삭제 예약이 존재하는 경우
#         # =================================================

#         if (
#             scheduled_delete_at
#             is not None
#         ):


#             print(
#                 f"recruit_id="
#                 f"{recruit_id} | "
#                 f"삭제 예정="
#                 f"{scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}"
#             )


#             # ---------------------------------------------
#             # 아직 삭제 시간이 안 됐으면 대기
#             # ---------------------------------------------

#             if (
#                 now
#                 < scheduled_delete_at
#             ):

#                 print(
#                     "→ 아직 유예기간 중"
#                 )

#                 continue


#             # ---------------------------------------------
#             # 안전장치
#             #
#             # 경고 후 활동이 있었다면
#             # 삭제하면 안 된다.
#             #
#             # 정상적으로 on_message가 처리됐다면
#             # 이미 scheduled_delete_at이 None이어야 하지만
#             # 실서비스에서는 DB 상태 경쟁 등을 대비해
#             # 삭제 직전 한 번 더 확인한다.
#             # ---------------------------------------------

#             if (
#                 inactivity_warned_at
#                 is not None

#                 and

#                 last_activity_at
#                 is not None

#                 and

#                 last_activity_at
#                 > inactivity_warned_at
#             ):

#                 print(
#                     f"경고 이후 활동 발견: "
#                     f"recruit_id="
#                     f"{recruit_id}"
#                 )


#                 meeting[
#                     "inactivity_warned_at"
#                 ] = None


#                 meeting[
#                     "scheduled_delete_at"
#                 ] = None


#                 print(
#                     "→ 자동삭제 예약 취소"
#                 )

#                 continue


#             # ---------------------------------------------
#             # 3. 유예기간 종료
#             #    → 실제 Discord 공간 삭제
#             # ---------------------------------------------

#             print(
#                 f"\n[상시모임 자동 종료 대상]\n"
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )


#             deleted = (
#                 await delete_meeting_space(
#                     guild=guild,
#                     category_id=category_id,
#                 )
#             )


#             if deleted:

#                 meeting[
#                     "discord_deleted_at"
#                 ] = now


#                 print(
#                     f"\n[상시모임 자동 종료 성공]\n"
#                     f"recruit_id="
#                     f"{recruit_id}\n"
#                     f"discord_deleted_at="
#                     f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
#                 )


#                 # 실제 서비스에서는 여기서
#                 #
#                 # recruits 상태 = CLOSED
#                 #
#                 # recruit_discord_channels
#                 # .discord_deleted_at = now
#                 #
#                 # DB UPDATE 예정


#             continue


#         # =================================================
#         # 4. 삭제 예약이 아직 없는 모임
#         #
#         # 30일 비활성 여부 확인
#         # =================================================

#         if last_activity_at is None:

#             print(
#                 f"last_activity_at 없음: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )

#             continue


#         inactive_duration = (
#             now
#             - last_activity_at
#         )


#         print(
#             f"recruit_id="
#             f"{recruit_id} | "
#             f"비활성 기간="
#             f"{inactive_duration.days}일"
#         )


#         # 아직 30일 미만
#         if (
#             inactive_duration
#             < timedelta(
#                 days=INACTIVITY_DAYS
#             )
#         ):

#             continue


#         # -------------------------------------------------
#         # 이미 경고를 보낸 경우
#         #
#         # 정상적으로는 scheduled_delete_at도
#         # 존재해야 하므로 별도 DM은 보내지 않는다.
#         # -------------------------------------------------

#         if (
#             inactivity_warned_at
#             is not None
#         ):

#             print(
#                 f"이미 비활성 경고됨: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )

#             continue


#         # =================================================
#         # 5. 30일 비활성
#         #    → HOST에게 경고 DM
#         # =================================================

#         try:

#             host = (
#                 await guild.fetch_member(
#                     host_id
#                 )
#             )


#             scheduled_delete_at = (
#                 now
#                 + timedelta(
#                     days=
#                     INACTIVITY_GRACE_DAYS
#                 )
#             )


#             await host.send(
#                 "PlayMate 모임 활동 안내\n\n"

#                 f"모임(recruit_id="
#                 f"{recruit_id})에서 "

#                 f"최근 "
#                 f"{INACTIVITY_DAYS}일 동안 "

#                 "Discord 활동이 "
#                 "확인되지 않았습니다.\n\n"

#                 f"앞으로 "
#                 f"{INACTIVITY_GRACE_DAYS}일 동안 "

#                 "활동이 없으면 "
#                 "모임이 자동 종료되고 "

#                 "Discord 공간이 "
#                 "삭제됩니다.\n\n"

#                 "모임 채널에서 "
#                 "다시 활동이 발생하면 "

#                 "자동 종료 예약은 "
#                 "취소됩니다."
#             )


#             meeting[
#                 "inactivity_warned_at"
#             ] = now


#             meeting[
#                 "scheduled_delete_at"
#             ] = (
#                 scheduled_delete_at
#             )


#             print(
#                 f"비활성 경고 DM 전송 완료: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )


#             print(
#                 f"자동 삭제 예정: "
#                 f"{scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}"
#             )


#         except discord.NotFound:

#             print(
#                 f"HOST를 찾을 수 없음: "
#                 f"host_id="
#                 f"{host_id}"
#             )


#         except discord.Forbidden:

#             print(
#                 f"HOST에게 DM을 "
#                 f"보낼 수 없음: "
#                 f"recruit_id="
#                 f"{recruit_id}"
#             )


#         except discord.HTTPException as e:

#             print(
#                 f"DM 전송 실패: "
#                 f"recruit_id="
#                 f"{recruit_id} / "
#                 f"{e}"
#             )


# # =========================================================
# # 9. Discord 준비 완료 전에 Task 시작 방지
# # =========================================================

# @check_inactive_ongoing_meetings.before_loop
# async def before_check_inactive_ongoing_meetings():

#     await client.wait_until_ready()


# # =========================================================
# # 10. Discord 로그인 완료
# # =========================================================

# @client.event
# async def on_ready():

#     print(
#         f"\nBot 로그인 성공: "
#         f"{client.user}"
#     )


#     guild = client.get_guild(
#         GUILD_ID
#     )


#     if guild is None:

#         print(
#             "테스트 서버를 "
#             "찾지 못했습니다."
#         )

#         return


#     print(
#         f"서버 연결 성공: "
#         f"{guild.name}"
#     )


#     print(
#         "상시모임 라이프사이클 "
#         "관리 준비 완료"
#     )


#     if not (
#         check_inactive_ongoing_meetings
#         .is_running()
#     ):

#         (
#             check_inactive_ongoing_meetings
#             .start()
#         )


#         if TEST_MODE:

#             print(
#                 "상시모임 상태 검사 시작 "
#                 "(테스트: 1분 주기)"
#             )

#         else:

#             print(
#                 "상시모임 상태 검사 시작 "
#                 "(실서비스: 하루 1회)"
#             )


# # =========================================================
# # 11. Bot 실행
# # =========================================================

# client.run(TOKEN)

"""PlayMate Discord Bot entry point and dependency wiring."""
import discord

from config import DB_CONFIGURED, GUILD_ID, TEST_MODE, TOKEN
from handlers.message_handler import handle_message
from repositories.meeting_repository import (
    InMemoryMeetingRepository,
    PostgresMeetingRepository,
)
from services.db_sync import create_sync_task
from services.lifecycle import create_lifecycle_task
from services.meeting_space import create_meeting_space, delete_meeting_space
from services.permissions import (
    grant_host_permissions,
    grant_participant_permissions,
    remove_participant_permissions,
)

# Preserve the original intents. Message content is not needed or stored.
intents = discord.Intents.default()
client = discord.Client(intents=intents)
# Persistent state lives in the shared PostgreSQL (recruit_discord_channels).
# Without DB settings the Bot keeps the original in-memory behaviour.
if DB_CONFIGURED:
    repository = PostgresMeetingRepository.from_env()
else:
    print('DB 설정이 없어 메모리 저장소를 사용합니다 (재시작 시 상태 유실).')
    repository = InMemoryMeetingRepository()
check_meeting_lifecycle = create_lifecycle_task(client, repository)
sync_db = create_sync_task(client, repository) if DB_CONFIGURED else None


@client.event
async def on_message(message: discord.Message):
    await handle_message(message, repository)


@client.event
async def on_ready():
    print(f'\nBot 로그인 성공: {client.user}')
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        print('테스트 서버를 찾지 못했습니다.')
        return
    print(f'서버 연결 성공: {guild.name}')
    print('PlayMate Discord Bot 라이프사이클 관리 준비 완료')
    if sync_db is not None and not sync_db.is_running():
        sync_db.start()
        print('PlayMate DB 동기화 시작')
    if not check_meeting_lifecycle.is_running():
        check_meeting_lifecycle.start()
        if TEST_MODE:
            print('모임 라이프사이클 검사 시작 (테스트: 1분 주기)')
        else:
            print('모임 라이프사이클 검사 시작 (실서비스: 하루 1회)')


if __name__ == "__main__":
    client.run(TOKEN)