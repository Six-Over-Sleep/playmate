"""모임 채널에 남아 있는 "탈퇴 회원의 잔여 권한"을 찾아 회수한다.

회원이 탈퇴하면 백엔드가 `members.discord_id`를 `w<member_id>`로 바꾸므로, 기존 참여자 동기화는 그 회원의
원래 Discord ID를 DB에서 더 이상 찾지 못한다. 그래서 Discord 쪽 채널의 사용자별 Permission Overwrite를 직접
읽어서 DB의 현재 자격자와 비교한다.

중요한 한계: DB에는 탈퇴 회원의 **원래 Discord ID가 남지 않는다.** 따라서 "이 overwrite의 주인이 탈퇴한 회원"이라고
개별 사용자 단위로는 확인할 수 없다. 운영자가 수동으로 권한을 준 운영진도 DB의 자격자 목록에는 없기 때문에,
"자격자가 아니다"만으로 지우면 운영진을 잘못 지운다. 그래서 개별 확인 대신 다음 근거를 **모두** 요구한다.

회수하려면 (모두 만족):
    1. 관리 대상 모임 채널이다 (DB의 SUCCESS 행, 텍스트 채널, 채널 주제의 모임 표지).
    2. 그 모임에 최근(기본 7일 이내) 탈퇴한 회원의 참여 기록이 있다 (탈퇴 근거). 근거가 없거나 오래됐으면
       남은 overwrite는 수동 권한일 수 있다 (탈퇴 직후라면 점검이 곧바로 정리하므로 오래 남지 않는다).
    3. 회수 후보 수가 그 모임의 탈퇴 회원 수를 넘지 않는다. 넘으면 누가 탈퇴 회원인지 알 수 없어 아무도 지우지 않는다.
    4. 이 Bot이 부여하는 권한과 정확히 같은 overwrite다 (보기/읽기/쓰기만). 다른 권한이 더 있으면 수동 부여로 본다.
    5. 보호 대상이 아니다: Role, 서버 소유자, Bot, 운영 권한 보유자(관리자, 채널/메시지/역할 관리, 추방/차단/타임아웃 등),
       운영진 역할(PLAYMATE_STAFF_ROLE_IDS), 보호 사용자(PLAYMATE_PROTECTED_USER_IDS).
    6. 그 채널의 모든 대상을 확인할 수 있었다 (확인 실패, 상한 초과 대상이 있으면 그 채널은 보류).
    7. DB 정보가 완전하고, 회수 직전에 DB 자격과 탈퇴 근거를 다시 읽어도 같다.
회수 대상이 아니면 로그에 "수동 확인 필요"와 사유를 남기고 권한은 그대로 둔다.

기본은 dry-run(로그만)이며, 실제 회수는 PLAYMATE_STRAY_REVOKE_ENABLED=true일 때만 한다. DB 락은 잡지 않는다
(공유 연결의 단순 조회만 사용). 실패는 (채널, 사용자)별로 지수 backoff한다.
"""
import asyncio
import re
from datetime import datetime, timedelta

import discord

from config import (
    DISCORD_CALL_TIMEOUT_SECONDS,
    KST,
    STRAY_AUDIT_INTERVAL_SECONDS,
    STRAY_PROTECTED_USER_IDS,
    STRAY_REVOKE_ENABLED,
    STRAY_STAFF_ROLE_IDS,
    SYNC_BACKOFF_BASE_SECONDS,
    STRAY_WITHDRAWN_WINDOW_DAYS,
    SYNC_BACKOFF_MAX_SECONDS,
    SYNC_MAX_CHANGES_PER_POLL,
)
from logging_setup import mask_id
from repositories.meeting_repository import call
from services.meeting_space import PARTICIPANT_PERMISSIONS, participant_overwrite, resolve_channel

# 탈퇴 회원의 식별 값 (백엔드 withdraw_member가 'w' + member_id로 바꾼다).
WITHDRAWN_DISCORD_ID = re.compile(r"^w\d+$")
# 한 번의 점검에서 Discord에 확인(멤버 조회)하는 대상 수 상한. 실제 회수 수 상한(SYNC_MAX_CHANGES_PER_POLL)과 별개다.
EVALUATION_LIMIT = SYNC_MAX_CHANGES_PER_POLL * 5
# 같은 대상에 대한 안내 로그를 반복하지 않는 간격.
LOG_INTERVAL = timedelta(hours=1)
# 이 권한을 가진 멤버는 운영진으로 보고 보호한다 (역할을 따로 지정하지 않아도 보호된다).
STAFF_PERMISSIONS = (
    "administrator", "manage_guild", "manage_channels", "manage_roles", "manage_messages",
    "kick_members", "ban_members", "moderate_members",
)


def _to_id(value) -> int | None:
    """DB의 문자열 Discord ID를 정수로 바꾼다. 쓸 수 없는 값은 None."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def classify_members(rows: list[dict]) -> dict:
    """한 모임의 DB 행(참여자 목록)을 자격 판정에 쓰는 집합으로 나눈다.

    반환:
        eligible: 현재 접근 자격이 있는 Discord ID (JOINED, 탈퇴가 아닌 회원. HOST 포함)
        canceled: 참여를 취소한 회원 (일반 동기화가 회수하므로 이 점검의 대상이 아님)
        hosts: HOST 회원의 Discord ID (어떤 상태에서도 이 점검이 회수하지 않는다)
        withdrawn: 이 모임의 최근 탈퇴 회원 수 (JOINED/CANCELED 기록 기준, STRAY_WITHDRAWN_WINDOW_DAYS 이내).
            탈퇴 근거이자 회수 수의 상한이다.
        complete: DB 정보가 판정에 충분한지. False면 이 모임은 점검하지 않는다.
        reason: complete가 False인 이유
    """
    eligible, canceled, hosts = set(), set(), set()
    withdrawn_count = 0
    complete, reason = True, ""
    for row in rows:
        status = row.get("status")
        if status is None:
            continue  # 참여자 행이 없는 모임 (LEFT JOIN)
        raw_id = row.get("discord_id")
        withdrawn_id = isinstance(raw_id, str) and bool(WITHDRAWN_DISCORD_ID.match(raw_id))
        withdrawn = withdrawn_id or row.get("member_status") == "WITHDRAWN"
        discord_id = None if withdrawn_id else _to_id(raw_id)
        if status not in ("JOINED", "CANCELED"):
            complete, reason = False, f"알 수 없는 참여 상태 {status!r}"
            continue
        if withdrawn and row.get("withdrawn_recent") is True:
            withdrawn_count += 1  # 탈퇴한 지 얼마 안 된 기록만 근거로 쓴다 (값을 모르면 근거로 쓰지 않는다)
        if withdrawn_id:
            continue  # 원래 Discord ID를 알 수 없는 탈퇴 회원: 자격자도 아니고 식별할 수도 없다
        if discord_id is None:
            if status == "JOINED":
                complete, reason = False, "JOINED 회원의 Discord ID를 쓸 수 없음"
            continue
        if row.get("role") == "HOST":
            hosts.add(discord_id)
        if withdrawn:
            continue  # 탈퇴 상태인데 숫자 ID가 남은 회원: 자격 없음 (잔여 권한이 있으면 회수 후보)
        (eligible if status == "JOINED" else canceled).add(discord_id)
    if complete and not eligible:
        complete, reason = False, "접근 자격이 있는 참여자가 한 명도 조회되지 않음"
    return {"eligible": eligible, "canceled": canceled, "hosts": hosts, "withdrawn": withdrawn_count,
            "complete": complete, "reason": reason}


def _has_access(overwrite: discord.PermissionOverwrite, visibility: str) -> bool:
    """사용자 overwrite가 이 채널에 대한 접근을 열어 주고 있는지 (읽기 전용으로 회수된 상태는 접근 아님)."""
    if overwrite.send_messages is True:
        return True
    if visibility.upper() == "PRIVATE":
        return any(getattr(overwrite, flag) is True for flag in PARTICIPANT_PERMISSIONS)
    return False


def _is_standard_overwrite(overwrite: discord.PermissionOverwrite) -> bool:
    """이 Bot이 참여자에게 부여하는 overwrite와 정확히 같은지. 다른 권한이 있으면 운영자가 수동으로 준 것으로 본다."""
    return overwrite.pair() == participant_overwrite().pair()


class StrayPermissionAudit:
    """주기적으로 모임 채널의 잔여 권한을 점검한다 (`run`). 상태는 로그 중복 방지와 backoff뿐이다."""

    def __init__(self, client, repository, visibility: str = "PUBLIC"):
        self.client = client
        self.repository = repository
        self.visibility = visibility
        self._last_run: datetime | None = None
        self._failures: dict[tuple, tuple[int, datetime]] = {}
        self._logged: dict[tuple, datetime] = {}

    # -- backoff / 로그 ------------------------------------------------
    def _blocked(self, key, now: datetime) -> bool:
        entry = self._failures.get(key)
        return entry is not None and entry[1] > now

    def _note_failure(self, key, now: datetime, label: str, error) -> None:
        count = self._failures.get(key, (0, now))[0] + 1
        delay = min(SYNC_BACKOFF_BASE_SECONDS * 2 ** (count - 1), SYNC_BACKOFF_MAX_SECONDS)
        self._failures[key] = (count, now + timedelta(seconds=delay))
        print(f"[권한 점검] 확인/회수 실패 {label} 연속 {count}회 {type(error).__name__} → {delay}초 후 재시도")

    def _log_once(self, key, now: datetime, message: str) -> None:
        """같은 대상/사유의 안내는 LOG_INTERVAL에 한 번만 남긴다."""
        if now - self._logged.get(key, now - LOG_INTERVAL * 2) >= LOG_INTERVAL:
            self._logged[key] = now
            print(message)

    # -- 판정 ----------------------------------------------------------
    async def _find_member(self, guild, user_id: int):
        """(멤버 또는 None, 서버에 없음 여부). 확인할 수 없는 오류는 예외로 올린다."""
        try:
            member = await asyncio.wait_for(guild.fetch_member(user_id), DISCORD_CALL_TIMEOUT_SECONDS)
        except discord.NotFound:
            return None, True
        return member, False

    def _protected_by_id(self, guild, user_id: int) -> str | None:
        """API 호출 없이 알 수 있는 보호 사유: Bot 자신, 서버 소유자, 운영자가 지정한 보호 사용자."""
        bot_user = getattr(self.client, "user", None)
        me = getattr(guild, "me", None)
        if user_id in {getattr(bot_user, "id", None), getattr(me, "id", None)}:
            return "Bot 자신"
        if user_id == getattr(guild, "owner_id", None):
            return "서버 소유자"
        if user_id in STRAY_PROTECTED_USER_IDS:
            return "보호 사용자(PLAYMATE_PROTECTED_USER_IDS)"
        return None

    def _protected_by_member(self, member) -> str | None:
        """멤버 정보로 알 수 있는 보호 사유: 다른 Bot, 운영 권한 보유자, 운영진 역할. 권한을 모르면 보호한다."""
        if getattr(member, "bot", False):
            return "Bot 계정"
        permissions = getattr(member, "guild_permissions", None)
        if permissions is None:
            return "권한 확인 불가"
        if any(getattr(permissions, name, False) for name in STAFF_PERMISSIONS):
            return "운영 권한 보유"
        role_ids = {getattr(role, "id", None) for role in (getattr(member, "roles", None) or [])}
        if role_ids & STRAY_STAFF_ROLE_IDS:
            return "운영진 역할(PLAYMATE_STAFF_ROLE_IDS)"
        return None

    async def _evaluate(self, guild, user_id: int, overwrite) -> dict:
        """개별 대상의 판정: protected(보호) / manual(수동 부여 가능성) / revocable(회수 후보). 확인 실패는 예외."""
        reason = self._protected_by_id(guild, user_id)
        if reason is not None:
            return {"kind": "protected", "reason": reason}
        if not _is_standard_overwrite(overwrite):
            return {"kind": "manual", "reason": "이 Bot이 부여하는 권한과 다른 overwrite(수동 부여 가능성)"}
        member, left_server = await self._find_member(guild, user_id)
        if member is not None:
            reason = self._protected_by_member(member)
            if reason is not None:
                return {"kind": "protected", "reason": reason}
        return {"kind": "revocable", "member": member, "left_server": left_server}

    async def _revoke(self, channel, user_id: int, member) -> None:
        """사용자 overwrite를 제거한다. 서버를 떠난 사용자는 공개 API(set_permissions)가 대상 객체를 받지 않아 HTTP 호출로 제거한다.

        `HTTPClient.delete_channel_permissions(channel_id, target_id)`는 set_permissions(overwrite=None)이 내부에서
        부르는 것과 같은 호출이다 (tests/test_permission_audit.py가 설치된 discord.py의 시그니처를 확인한다).
        """
        if member is not None:
            await asyncio.wait_for(channel.set_permissions(member, overwrite=None), DISCORD_CALL_TIMEOUT_SECONDS)
            return
        http = getattr(getattr(channel, "_state", None), "http", None)
        if http is None:
            raise RuntimeError("서버를 떠난 사용자의 overwrite를 제거할 수 없음")
        await asyncio.wait_for(http.delete_channel_permissions(channel.id, user_id), DISCORD_CALL_TIMEOUT_SECONDS)

    # -- 점검 한 번 ----------------------------------------------------
    async def run(self, guild, now: datetime | None = None) -> dict | None:
        """점검 한 번. STRAY_AUDIT_INTERVAL_SECONDS가 지나지 않았으면 건너뛴다. 결과 요약을 돌려준다.

        DB 조회가 실패하면 예외를 올린다 (회수는 하지 않는다). 개별 사용자의 실패는 backoff로 격리한다.
        """
        now = now or datetime.now(KST)
        if self._last_run is not None and (now - self._last_run).total_seconds() < STRAY_AUDIT_INTERVAL_SECONDS:
            return None
        self._last_run = now
        rows = await call(self.repository.list_audit_rows)
        by_channel: dict[int, list[dict]] = {}
        for row in rows:
            channel_id = _to_id(row.get("discord_text_channel_id"))
            if channel_id is not None:
                by_channel.setdefault(channel_id, []).append(row)

        summary = {"channels": 0, "skipped_channels": 0, "candidates": 0, "protected": 0, "manual": 0,
                   "dry_run": 0, "revoked": 0, "failed": 0, "deferred": 0}
        live_keys: set = set()
        attempts = revocations = 0
        for channel_id, channel_rows in by_channel.items():
            recruit_id = channel_rows[0]["recruit_id"]
            members = classify_members(channel_rows)
            state, channel = await resolve_channel(guild, channel_id)
            marker = f"PlayMate 모임 #{recruit_id} "
            if (state != "present" or getattr(channel, "type", None) is not discord.ChannelType.text
                    or not (getattr(channel, "topic", None) or "").startswith(marker)):
                summary["skipped_channels"] += 1
                continue  # 채널을 정확히 식별할 수 없으면 아무것도 하지 않는다
            if not members["complete"]:
                summary["skipped_channels"] += 1
                print(f"[권한 점검] DB 정보가 불완전해 건너뜀 recruit_id={recruit_id}: {members['reason']}")
                continue
            summary["channels"] += 1
            known = members["eligible"] | members["canceled"] | members["hosts"]
            pending = []
            for target, overwrite in list(channel.overwrites.items()):
                if isinstance(target, discord.Role) or (
                        isinstance(target, discord.Object) and target.type is discord.Role):
                    continue  # Role overwrite는 점검 대상이 아니다
                if target.id in known or not _has_access(overwrite, self.visibility):
                    continue
                pending.append((target.id, overwrite))
            if not pending:
                continue

            # 1단계: 대상마다 판정한다. 하나라도 확인하지 못하면(uncertain) 이 채널은 이번에 회수하지 않는다.
            verdicts: dict[int, dict] = {}
            uncertain = False
            for user_id, overwrite in pending:
                key = (channel_id, user_id)
                live_keys.add(key)
                summary["candidates"] += 1
                label = f"recruit_id={recruit_id} channel_id={channel_id} user={mask_id(user_id)}"
                if self._blocked(key, now):
                    uncertain = True  # 이전 실패의 backoff 중인 대상은 아직 확인하지 못한 것이므로 이 채널은 보류한다
                    continue
                if attempts >= EVALUATION_LIMIT:
                    summary["deferred"] += 1
                    uncertain = True
                    continue
                attempts += 1
                try:
                    verdicts[user_id] = await self._evaluate(guild, user_id, overwrite)
                except Exception as error:
                    summary["failed"] += 1
                    uncertain = True
                    self._note_failure(key, now, label, error)
            revocable = [u for u, v in verdicts.items() if v["kind"] == "revocable"]
            for user_id, verdict in verdicts.items():
                label = f"recruit_id={recruit_id} channel_id={channel_id} user={mask_id(user_id)}"
                if verdict["kind"] == "protected":
                    summary["protected"] += 1
                    self._log_once((channel_id, user_id, "보호"), now,
                                   f"[권한 점검] 보호 대상이라 회수하지 않음({verdict['reason']}) {label}")
                elif verdict["kind"] == "manual":
                    summary["manual"] += 1
                    self._log_once((channel_id, user_id, "수동"), now,
                                   f"[권한 점검] 수동 확인 필요 — 회수하지 않음 {label}: {verdict['reason']}")

            # 2단계: 채널 단위 근거 확인. 개별 사용자가 탈퇴 회원인지는 알 수 없으므로 수와 증거로 제한한다.
            total_revocable = len(revocable)
            hold = None
            if uncertain:
                hold = "확인하지 못한 대상이 있어 판단 보류"
            elif members["withdrawn"] == 0:
                hold = (f"최근 {STRAY_WITHDRAWN_WINDOW_DAYS}일 이내 탈퇴 회원 기록이 없음 "
                        "(수동으로 준 권한일 수 있음)")
            elif total_revocable > members["withdrawn"]:
                hold = (f"회수 후보 {total_revocable}명이 탈퇴 회원 {members['withdrawn']}명보다 많아 "
                        "누가 탈퇴 회원인지 알 수 없음")
            if hold is not None:
                for user_id in revocable:
                    summary["manual"] += 1
                    self._log_once((channel_id, user_id, "수동"), now,
                                   f"[권한 점검] 수동 확인 필요 — 회수하지 않음 recruit_id={recruit_id} "
                                   f"channel_id={channel_id} user={mask_id(user_id)}: {hold}")
                continue

            # 3단계: 회수(또는 dry-run 기록). 근거를 로그에 함께 남긴다.
            evidence = f"탈퇴 회원 {members['withdrawn']}명 중 회수 후보 {total_revocable}명, 표준 overwrite"
            for user_id in revocable:
                key = (channel_id, user_id)
                label = f"recruit_id={recruit_id} channel_id={channel_id} user={mask_id(user_id)}"
                verdict = verdicts[user_id]
                if not STRAY_REVOKE_ENABLED:
                    summary["dry_run"] += 1
                    where = "서버에 없음" if verdict["left_server"] else "서버 멤버"
                    self._log_once((channel_id, user_id, "dry"), now,
                                   f"[권한 점검] (dry-run) 회수 대상 {label} ({where}) 근거: {evidence} — 실제 회수는 "
                                   "PLAYMATE_STRAY_REVOKE_ENABLED=true일 때만 합니다")
                    continue
                if revocations >= SYNC_MAX_CHANGES_PER_POLL:
                    summary["deferred"] += 1  # 실패가 아니므로 다음 점검에서 이어서 처리한다
                    continue
                revocations += 1
                try:
                    # 회수 직전에 DB 자격과 탈퇴 근거를 다시 읽어, 그사이 바뀐 상태로 잘못 지우지 않는다.
                    fresh = classify_members(await call(self.repository.list_audit_rows, recruit_id))
                    if (not fresh["complete"] or total_revocable > fresh["withdrawn"]
                            or user_id in (fresh["eligible"] | fresh["canceled"] | fresh["hosts"])):
                        print(f"[권한 점검] 회수 직전 재확인에서 대상이 아니어서 건너뜀 {label}")
                        continue
                    await self._revoke(channel, user_id, verdict["member"])
                    summary["revoked"] += 1
                    self._failures.pop(key, None)
                    print(f"[권한 점검] 잔여 권한 회수 완료 {label} 근거: {evidence}")
                except Exception as error:
                    summary["failed"] += 1
                    self._note_failure(key, now, label, error)
        # 더 이상 대상이 아닌 키의 기록은 지운다.
        for key in [k for k in self._failures if k not in live_keys]:
            del self._failures[key]
        for key in [k for k in self._logged if k[:2] not in live_keys]:
            del self._logged[key]
        mode = "실제 회수" if STRAY_REVOKE_ENABLED else "dry-run"
        print(f"[권한 점검] 완료({mode}): 점검 채널 {summary['channels']}개, 대상 {summary['candidates']}명, "
              f"회수 {summary['revoked']}, dry-run {summary['dry_run']}, 보호 {summary['protected']}, "
              f"수동 확인 {summary['manual']}, 실패 {summary['failed']}")
        return summary
