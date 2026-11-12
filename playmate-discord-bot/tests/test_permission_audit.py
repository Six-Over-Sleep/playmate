"""탈퇴 회원 등 자격 없는 사용자의 잔여 채널 권한 점검(permission_audit) 테스트.

1부(mock): Discord와 DB 없이 판정 기준, dry-run, 보호 대상, 오류 처리, 멱등성을 가짜 객체로 확인한다.
2부(DB): 일회용 로컬 PostgreSQL(PLAYMATE_TEST_PG_DSN)과 가짜 Discord로 실제 SQL, 탈퇴 처리, 동시성을 확인한다.
실제 Discord 서버나 공용 DB에는 연결하지 않는다. 실제 Discord 동작은 이 테스트로 증명하지 않는다.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DISCORD_BOT_TOKEN"] = "verification-only"
os.environ["DISCORD_GUILD_ID"] = "1"
# 로컬 .env의 운영 설정이 테스트 기본값을 바꾸거나 운영 DB로 연결되지 않게 비운다 (환경변수가 .env보다 우선).
for _name in ("PLAYMATE_CATCHUP_DAYS", "PLAYMATE_PROVISION_BATCH_LIMIT", "PLAYMATE_SYNC_MAX_CHANGES",
              "PLAYMATE_STRAY_REVOKE_ENABLED", "PLAYMATE_STRAY_AUDIT_INTERVAL_SECONDS",
              "PLAYMATE_STRAY_WITHDRAWN_WINDOW_DAYS", "PLAYMATE_STAFF_ROLE_IDS", "PLAYMATE_PROTECTED_USER_IDS",
              "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_SSLMODE"):
    os.environ[_name] = ""

import discord

import config
import services.db_sync as db_sync_module
import services.permission_audit as audit_module
from config import KST
from services.meeting_space import participant_overwrite
from services.permission_audit import StrayPermissionAudit, classify_members

DSN = os.environ.get("PLAYMATE_TEST_PG_DSN")
T0 = datetime(2026, 11, 12, 12, 0, tzinfo=KST)
checks = 0


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


def api_error(kind):
    status = {"NotFound": 404, "Forbidden": 403, "HTTPException": 500}[kind]
    return getattr(discord, kind)(SimpleNamespace(status=status, reason="test"), "test")


# ------------------------------------------------------------------ 가짜 Discord / 저장소
class FUser:
    """overwrite 키와 fetch_member 결과로 쓰는 가짜 사용자."""

    def __init__(self, user_id, *, bot=False, admin=False):
        self.id, self.bot = user_id, bot
        self.guild_permissions = SimpleNamespace(administrator=admin)

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id


class FHttp:
    def __init__(self, channel):
        self.channel, self.calls = channel, []

    async def delete_channel_permissions(self, channel_id, user_id):
        self.calls.append(user_id)
        self.channel._drop(user_id)


class FChannel:
    def __init__(self, channel_id, recruit_id, *, topic=True, channel_type=discord.ChannelType.text):
        self.id, self.type = channel_id, channel_type
        self.topic = f"PlayMate 모임 #{recruit_id} (PUBLIC)" if topic else "다른 채널"
        self.overwrites, self.calls, self.fail = {}, [], None
        self._state = SimpleNamespace(http=FHttp(self))

    def _drop(self, user_id):
        for key in [k for k in self.overwrites if k.id == user_id]:
            del self.overwrites[key]

    async def set_permissions(self, target, overwrite=None):
        self.calls.append((target.id, overwrite))
        if self.fail is not None:
            raise self.fail
        if overwrite is None:
            self._drop(target.id)
        else:
            self.overwrites[target] = overwrite

    def grant(self, user_id):
        self.overwrites[FUser(user_id)] = participant_overwrite()


class FGuild:
    def __init__(self):
        self.channels, self.members, self.owner_id = {}, {}, 999
        self.me = SimpleNamespace(id=998)
        self.fetch_calls, self.on_fetch = [], None

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id):
        raise api_error("NotFound")

    async def fetch_member(self, user_id):
        self.fetch_calls.append(user_id)
        if self.on_fetch is not None:
            result = self.on_fetch()
            if asyncio.iscoroutine(result):
                await result
        found = self.members.get(user_id, FUser(user_id))
        if isinstance(found, Exception):
            raise found
        if found == "hang":
            await asyncio.sleep(30)
        return found


class FRepo:
    """list_audit_rows만 가진 가짜 저장소. calls로 재확인 조회 횟수를 센다."""

    def __init__(self, rows):
        self.rows, self.calls, self.fail, self.after_first = rows, 0, None, None

    def list_audit_rows(self, recruit_id=None):
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        if self.calls > 1 and self.after_first is not None:
            self.rows = self.after_first
        return [dict(r) for r in self.rows if recruit_id is None or r["recruit_id"] == recruit_id]


def row(status, discord_id, role="MEMBER", member_status="ACTIVE", recruit_id=1, channel_id=100, recent=True):
    """DB 행 하나. recent는 탈퇴한 지 얼마 안 됐는지(withdrawn_recent)다."""
    return {"recruit_id": recruit_id, "discord_text_channel_id": str(channel_id), "status": status,
            "role": role, "discord_id": discord_id, "member_status": member_status, "withdrawn_recent": recent}


def withdrawn_rows(count, recent=True):
    """탈퇴 회원 행 count개 (백엔드 withdraw_member 결과와 같은 'w<id>' 값)."""
    return [row("JOINED", f"w{100 + i}", member_status="WITHDRAWN", recent=recent) for i in range(count)]


def setup(rows, *, granted=(1001, 1002), strays=(7777,), recruit_id=1, channel_id=100):
    guild = FGuild()
    channel = FChannel(channel_id, recruit_id)
    for user_id in (*granted, *strays):
        channel.grant(user_id)
    guild.channels[channel_id] = channel
    client = SimpleNamespace(user=SimpleNamespace(id=998))
    repo = FRepo(rows)
    return guild, channel, repo, StrayPermissionAudit(client, repo)


BASE_ROWS = [row("JOINED", "1001", role="HOST"), row("JOINED", "1002"),
             row("JOINED", "w5", member_status="WITHDRAWN")]


def has(channel, user_id):
    return any(k.id == user_id for k in channel.overwrites)


class Mode:
    """STRAY_REVOKE_ENABLED 등 모듈 상수를 시험 중에만 바꾼다."""

    def __init__(self, **values):
        self.values, self.saved = values, {}

    def __enter__(self):
        for name, value in self.values.items():
            self.saved[name] = getattr(audit_module, name)
            setattr(audit_module, name, value)

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(audit_module, name, value)


async def run_at(audit, guild, seconds=0):
    return await audit.run(guild, T0 + timedelta(seconds=seconds))


# ------------------------------------------------------------------ 1부: mock
def test_classify():
    result = classify_members(BASE_ROWS + [row("CANCELED", "1003"), row("JOINED", "1004", role="HOST")])
    check(result["eligible"] == {1001, 1002, 1004} and result["canceled"] == {1003} and result["hosts"] == {1001, 1004}
          and result["complete"], "JOINED(HOST 포함)는 자격자, CANCELED는 별도, 탈퇴('w..')는 식별 불가라 제외")
    check(classify_members([row("JOINED", " 1001 ")])["eligible"] == {1001}, "문자열 ID(공백 포함)도 정수로 비교")
    for label, rows in (
        ("자격자 0명", [row("CANCELED", "1003")]),
        ("참여자 행 없음", [row(None, None)]),
        ("JOINED의 ID가 NULL", [row("JOINED", "1001"), row("JOINED", None)]),
        ("JOINED의 ID가 숫자가 아님", [row("JOINED", "1001"), row("JOINED", "abc")]),
        ("알 수 없는 상태", [row("JOINED", "1001"), row("PENDING", "1002")]),
    ):
        check(classify_members(rows)["complete"] is False, f"{label}: DB 정보가 불완전하면 점검하지 않는다")
    check(classify_members([row("JOINED", "1001"), row("CANCELED", "abc")])["complete"] is True,
          "취소한 회원의 잘못된 ID는 판정을 막지 않는다")
    withdrawn = classify_members([row("JOINED", "1001"), row("JOINED", "2002", member_status="WITHDRAWN")])
    check(withdrawn["eligible"] == {1001}, "탈퇴 상태인데 숫자 ID가 남은 회원은 자격자가 아니다")
    check(classify_members(BASE_ROWS)["withdrawn"] == 1, "탈퇴 근거 수: 최근 탈퇴 회원 1명")
    check(classify_members([row("JOINED", "1001")] + withdrawn_rows(2, recent=False))["withdrawn"] == 0,
          "탈퇴한 지 오래된 기록은 회수 근거로 쓰지 않는다")
    unknown_age = row("JOINED", "w9", member_status="WITHDRAWN")
    del unknown_age["withdrawn_recent"]
    check(classify_members([row("JOINED", "1001"), unknown_age])["withdrawn"] == 0, "탈퇴 시점을 모르면 근거로 쓰지 않는다")
    host = classify_members([row("JOINED", "1001"), row("JOINED", "2002", role="HOST", member_status="WITHDRAWN")])
    check(2002 in host["hosts"] and 2002 not in host["eligible"], "HOST는 어떤 경우에도 hosts로 보호 집합에 들어간다")


async def test_detect_and_modes():
    guild, channel, repo, audit = setup(BASE_ROWS)
    with Mode(STRAY_REVOKE_ENABLED=False):
        summary = await run_at(audit, guild)
    check(summary["candidates"] == 1 and summary["dry_run"] == 1 and summary["revoked"] == 0, "탈퇴 회원의 잔여 overwrite를 대상으로 식별")
    check(channel.calls == [] and has(channel, 7777), "dry-run에서는 권한 변경이 0회")
    check(repo.calls == 1, "dry-run은 회수 직전 재확인 조회도 하지 않는다")

    guild, channel, repo, audit = setup(BASE_ROWS)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
        check(summary["revoked"] == 1 and not has(channel, 7777), "실제 회수 모드에서는 탈퇴 회원의 권한을 제거한다")
        check(has(channel, 1001) and has(channel, 1002) and [c[0] for c in channel.calls] == [7777],
              "정상 HOST와 참여자의 권한은 유지되고 대상 한 명만 변경한다")
        check(repo.calls == 2, "회수 직전에 DB 자격을 다시 읽는다")
        check(await run_at(audit, guild, 60) is None, "점검 주기(300초) 안의 호출은 건너뛴다")
        again = await run_at(audit, guild, 301)
        check(again["candidates"] == 0 and len(channel.calls) == 1, "반복 실행은 멱등: 더 이상 변경하지 않는다")
        restarted = StrayPermissionAudit(SimpleNamespace(user=SimpleNamespace(id=998)), repo)
        again = await run_at(restarted, guild, 700)
        check(again["candidates"] == 0 and len(channel.calls) == 1, "재시작(새 인스턴스)해도 멱등")


async def test_protection():
    rows = BASE_ROWS + [row("CANCELED", "1003")]
    guild, channel, repo, audit = setup(rows, granted=(1001, 1002, 1003), strays=(8001, 8002, 8003, 8004))
    guild.members[8001] = FUser(8001, admin=True)   # 서버 관리자
    guild.members[8002] = FUser(8002, bot=True)     # 다른 Bot
    guild.owner_id = 8003                           # 서버 소유자
    channel.overwrites[FUser(998)] = participant_overwrite()  # Bot 자신
    channel.overwrites[discord.Object(id=900, type=discord.Role)] = participant_overwrite()  # Role overwrite
    guild.members[8004] = SimpleNamespace(id=8004, bot=False)  # 권한을 알 수 없는 멤버
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(channel.calls == [] and summary["revoked"] == 0, "관리자/Bot/소유자/Role/권한 불명 멤버는 회수하지 않는다")
    check(summary["protected"] == 5 and has(channel, 8001) and has(channel, 998), "보호 사유별로 건너뛴다")
    check(has(channel, 1003), "참여 취소자(1003)는 이 점검의 대상이 아니다 (일반 동기화가 회수)")


async def test_incomplete_and_identification():
    for label, rows in (("자격자 0명", [row("CANCELED", "1003")]),
                        ("JOINED의 ID NULL", [row("JOINED", "1001"), row("JOINED", None)]),
                        ("알 수 없는 상태", [row("JOINED", "1001"), row("PENDING", "1002")])):
        guild, channel, repo, audit = setup(rows)
        with Mode(STRAY_REVOKE_ENABLED=True):
            summary = await run_at(audit, guild)
        check(channel.calls == [] and summary["skipped_channels"] == 1, f"{label}: DB 정보가 불완전하면 회수하지 않는다")

    guild, channel, repo, audit = setup(BASE_ROWS)
    repo.fail = RuntimeError("db down")
    with Mode(STRAY_REVOKE_ENABLED=True):
        try:
            await run_at(audit, guild)
            raised = False
        except RuntimeError:
            raised = True
    check(raised and channel.calls == [], "DB 조회가 실패하면 예외를 올리고 회수하지 않는다")

    for label, channel_fix in (("모임 표지 불일치", lambda c: setattr(c, "topic", "PlayMate 모임 #2 (PUBLIC)")),
                               ("텍스트 채널 아님", lambda c: setattr(c, "type", discord.ChannelType.category))):
        guild, channel, repo, audit = setup(BASE_ROWS)
        channel_fix(channel)
        with Mode(STRAY_REVOKE_ENABLED=True):
            summary = await run_at(audit, guild)
        check(channel.calls == [] and summary["skipped_channels"] == 1, f"{label}: 채널을 식별할 수 없으면 회수하지 않는다")
    guild, channel, repo, audit = setup(BASE_ROWS)
    guild.channels.clear()  # 캐시에 없고 fetch_channel도 NotFound
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["skipped_channels"] == 1 and summary["revoked"] == 0, "채널이 없으면 아무것도 하지 않는다")

    # DB의 문자열 ID와 Discord의 정수 ID 비교: 형 변환 때문에 정상 참여자를 지우지 않는다
    guild, channel, repo, audit = setup([row("JOINED", "0001001", role="HOST"), row("JOINED", " 1002 ")], strays=())
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["candidates"] == 0 and has(channel, 1001) and has(channel, 1002), "문자열 ID(앞 0, 공백)도 정상 참여자로 인식")


async def test_recheck_before_revoke():
    guild, channel, repo, audit = setup(BASE_ROWS)
    # 첫 조회에는 없던 사용자가 회수 직전 재조회에서는 참여자가 되어 있다 (예: 같은 Discord 계정으로 다시 가입해 참여)
    repo.after_first = BASE_ROWS + [row("JOINED", "7777")]
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and has(channel, 7777) and channel.calls == [], "회수 직전에 자격이 생기면 회수하지 않는다")

    guild, channel, repo, audit = setup(BASE_ROWS)
    repo.after_first = [row("CANCELED", "1003")]  # 재조회가 불완전하면 회수하지 않는다
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and channel.calls == [], "회수 직전 재조회가 불완전하면 회수하지 않는다")

    guild, channel, repo, audit = setup(BASE_ROWS)
    repo.after_first = [row("JOINED", "1001", role="HOST"), row("JOINED", "1002")] + withdrawn_rows(1, recent=False)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and channel.calls == [], "회수 직전 재조회에서 탈퇴 근거가 없어지면 회수하지 않는다")


async def test_discord_errors():
    # 멤버 확인 실패(Forbidden / HTTP 오류 / 시간 초과): 그 채널은 이번에 아무도 회수하지 않고(보류) backoff로 기록한다
    two_withdrawn = BASE_ROWS + withdrawn_rows(1)  # 탈퇴 회원 2명: 후보 2명이 모두 근거 범위 안이다
    for label, failure in (("Forbidden", api_error("Forbidden")), ("HTTPException", api_error("HTTPException")), ("시간 초과", "hang")):
        guild, channel, repo, audit = setup(two_withdrawn, strays=(7777, 7778))
        guild.members[7777] = failure
        original_timeout = audit_module.DISCORD_CALL_TIMEOUT_SECONDS
        audit_module.DISCORD_CALL_TIMEOUT_SECONDS = 0.05
        try:
            with Mode(STRAY_REVOKE_ENABLED=True):
                summary = await run_at(audit, guild)
        finally:
            audit_module.DISCORD_CALL_TIMEOUT_SECONDS = original_timeout
        check(summary["failed"] == 1 and summary["revoked"] == 0 and has(channel, 7777) and has(channel, 7778),
              f"{label}: 확인하지 못한 대상이 있으면 그 채널은 아무도 회수하지 않는다 (보류)")
        check(audit._failures[(100, 7777)][0] == 1, f"{label}: 실패가 backoff로 기록된다")
    # backoff 중에는 그 대상을 다시 확인하지 않고(채널은 계속 보류), 30초가 지나면 다시 확인해 회수한다
    guild.members[7777] = FUser(7777)
    with Mode(STRAY_REVOKE_ENABLED=True, STRAY_AUDIT_INTERVAL_SECONDS=10):  # 점검 주기를 줄여 backoff(30초)를 확인
        summary = await run_at(audit, guild, 10)
        check(guild.fetch_calls.count(7777) == 1 and summary["revoked"] == 0 and has(channel, 7777) and has(channel, 7778),
              "backoff 중에는 재확인하지 않고 채널을 보류한다")
        await run_at(audit, guild, 31)
    check(not has(channel, 7777) and not has(channel, 7778) and not audit._failures,
          "backoff 뒤 모두 확인되면 회수되고 실패 기록이 지워진다")

    # 권한 제거 호출 실패(Forbidden / NotFound / HTTPException): 예외 없이 실패로 기록하고 권한은 그대로
    for kind in ("Forbidden", "NotFound", "HTTPException"):
        guild, channel, repo, audit = setup(BASE_ROWS)
        channel.fail = api_error(kind)
        with Mode(STRAY_REVOKE_ENABLED=True):
            summary = await run_at(audit, guild)
        check(summary["failed"] == 1 and summary["revoked"] == 0 and has(channel, 7777) and has(channel, 1001),
              f"권한 제거 {kind}: 안전하게 실패하고 정상 권한은 유지")

    # 서버를 떠난 사용자(NotFound): HTTP 호출로 제거. 그것도 불가능하면 실패로만 기록
    guild, channel, repo, audit = setup(BASE_ROWS)
    guild.members[7777] = api_error("NotFound")
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 1 and channel._state.http.calls == [7777] and channel.calls == [] and not has(channel, 7777),
          "서버를 떠난 사용자의 잔여 overwrite도 제거한다")
    guild, channel, repo, audit = setup(BASE_ROWS)
    guild.members[7777] = api_error("NotFound")
    channel._state = None
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["failed"] == 1 and has(channel, 7777), "제거 수단이 없으면 예외 없이 실패로 기록")

    # 한 번에 처리하는 수 상한
    guild, channel, repo, audit = setup(BASE_ROWS + withdrawn_rows(4), strays=(7001, 7002, 7003, 7004, 7005))
    original_cap = audit_module.SYNC_MAX_CHANGES_PER_POLL
    audit_module.SYNC_MAX_CHANGES_PER_POLL = 2
    try:
        with Mode(STRAY_REVOKE_ENABLED=True):
            first = await run_at(audit, guild)
            second = await run_at(audit, guild, 301)
            third = await run_at(audit, guild, 602)
    finally:
        audit_module.SYNC_MAX_CHANGES_PER_POLL = original_cap
    check((first["revoked"], first["deferred"], second["revoked"], third["revoked"]) == (2, 3, 2, 1)
          and not any(has(channel, i) for i in range(7001, 7006)), "상한 2: 2 -> 2 -> 1건씩 이어서 처리 (실패 아님)")


async def test_manual_staff_protection():
    import contextlib
    import io

    def staff_overwrite(**extra):
        overwrite = participant_overwrite()
        for name, value in extra.items():
            setattr(overwrite, name, value)
        return overwrite

    # A) 수동으로 준 권한은 보통 이 Bot의 표준 overwrite와 다르다: 탈퇴 근거가 있어도 회수하지 않는다
    guild, channel, repo, audit = setup(BASE_ROWS, strays=())
    channel.overwrites[FUser(8101)] = staff_overwrite(manage_messages=True, embed_links=True)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and summary["manual"] == 1 and has(channel, 8101) and channel.calls == [],
          "표준과 다른 overwrite(수동 부여 가능성)는 탈퇴 근거가 있어도 회수하지 않는다")

    # B) 탈퇴 회원 기록이 없는 모임의 남은 overwrite(운영진이 표준과 같은 권한으로 준 경우)는 회수하지 않는다
    guild, channel, repo, audit = setup([row("JOINED", "1001", role="HOST"), row("JOINED", "1002")], strays=(8102,))
    out = io.StringIO()
    with Mode(STRAY_REVOKE_ENABLED=True), contextlib.redirect_stdout(out):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and summary["manual"] == 1 and has(channel, 8102),
          "탈퇴 근거가 없으면 자격자가 아니라는 이유만으로 회수하지 않는다")
    check("수동 확인 필요" in out.getvalue() and "탈퇴 회원 기록이 없음" in out.getvalue(),
          "로그에 '수동 확인 필요'와 사유(탈퇴 근거 없음)가 남는다")

    # C) 후보가 탈퇴 회원 수보다 많으면 누가 탈퇴 회원인지 알 수 없다: 아무도 회수하지 않는다
    guild, channel, repo, audit = setup(BASE_ROWS, strays=(7777, 8103))  # 탈퇴 1명, 후보 2명 (한 명은 운영진일 수 있음)
    out = io.StringIO()
    with Mode(STRAY_REVOKE_ENABLED=True), contextlib.redirect_stdout(out):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and summary["manual"] == 2 and has(channel, 7777) and has(channel, 8103),
          "후보 수가 탈퇴 회원 수보다 많으면 모두 보류한다")
    check("탈퇴 회원 1명보다 많아" in out.getvalue(), "로그에 후보 수와 탈퇴 회원 수가 함께 남는다")

    # D) 운영 권한을 가진 멤버 / 운영진 역할 / 보호 사용자는 보호된다 (표준 overwrite여도)
    guild, channel, repo, audit = setup(BASE_ROWS + withdrawn_rows(2), strays=(8201, 8202, 8203, 7777))
    guild.members[8201] = SimpleNamespace(id=8201, bot=False, guild_permissions=SimpleNamespace(manage_messages=True))
    guild.members[8202] = SimpleNamespace(id=8202, bot=False, guild_permissions=SimpleNamespace(),
                                          roles=[SimpleNamespace(id=555)])
    with Mode(STRAY_REVOKE_ENABLED=True, STRAY_STAFF_ROLE_IDS=frozenset({555}),
              STRAY_PROTECTED_USER_IDS=frozenset({8203})):
        summary = await run_at(audit, guild)
    check(summary["protected"] == 3 and summary["revoked"] == 1 and not has(channel, 7777)
          and all(has(channel, i) for i in (8201, 8202, 8203)),
          "운영 권한 보유, 운영진 역할, 보호 사용자는 회수하지 않고 일반 후보만 회수한다")

    # E) 탈퇴한 지 오래된 기록은 근거가 아니다 (오래 뒤에 남은 overwrite는 수동 권한일 수 있다)
    guild, channel, repo, audit = setup([row("JOINED", "1001", role="HOST"), row("JOINED", "1002")] + withdrawn_rows(1, recent=False))
    out = io.StringIO()
    with Mode(STRAY_REVOKE_ENABLED=True), contextlib.redirect_stdout(out):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and has(channel, 7777) and "최근 7일 이내 탈퇴 회원 기록이 없음" in out.getvalue(),
          "탈퇴한 지 기간이 지난 기록만 있으면 회수하지 않고 사유를 남긴다")

    # F) 회수되는 경우의 로그에는 판단 근거가 남는다 (dry-run / 실제 회수)
    for enabled, marker in ((False, "(dry-run) 회수 대상"), (True, "잔여 권한 회수 완료")):
        guild, channel, repo, audit = setup(BASE_ROWS)
        out = io.StringIO()
        with Mode(STRAY_REVOKE_ENABLED=enabled), contextlib.redirect_stdout(out):
            await run_at(audit, guild)
        check(marker in out.getvalue() and "근거: 탈퇴 회원 1명 중 회수 후보 1명, 표준 overwrite" in out.getvalue(),
              f"{marker} 로그에 판단 근거(탈퇴 회원 수, 후보 수, 표준 overwrite)가 남는다")


async def test_dry_run_never_writes():
    """dry-run에서는 어떤 경로로도 Discord 쓰기가 일어나지 않는다 (서버 멤버, 서버를 떠난 사용자, 보호 대상 포함)."""
    guild, channel, repo, audit = setup(BASE_ROWS + withdrawn_rows(2), strays=(7777, 7778, 7779))
    guild.members[7778] = api_error("NotFound")  # 서버를 떠난 사용자

    async def forbidden_write(*args, **kwargs):
        raise AssertionError("dry-run에서 Discord 쓰기가 호출되었다")

    channel.set_permissions = forbidden_write
    channel._state.http.delete_channel_permissions = forbidden_write
    audit._revoke = forbidden_write
    with Mode(STRAY_REVOKE_ENABLED=False):
        summary = await run_at(audit, guild)
    check(summary["dry_run"] == 3 and summary["revoked"] == 0 and summary["failed"] == 0
          and all(has(channel, i) for i in (7777, 7778, 7779)), "dry-run: 후보 3명을 식별하고 Discord 쓰기는 0회")


async def test_discord_py_compat():
    """설치된 discord.py에서 서버를 떠난 사용자의 overwrite를 제거하는 호출 방식이 유효한지 확인한다."""
    import inspect

    from discord.abc import GuildChannel
    from discord.http import HTTPClient

    check(discord.__version__.startswith("2."), f"discord.py 2.x ({discord.__version__})")
    params = list(inspect.signature(HTTPClient.delete_channel_permissions).parameters)
    check(params[:3] == ["self", "channel_id", "target"], f"HTTPClient.delete_channel_permissions 시그니처 {params}")

    calls = []

    class Http:
        async def delete_channel_permissions(self, channel_id, target, *, reason=None):
            calls.append((channel_id, target))

    real_channel = object.__new__(discord.TextChannel)  # 실제 discord.py 채널 객체 (서버 연결 없음)
    real_channel.id = 100
    real_channel._state = SimpleNamespace(http=Http())

    async def attempt():
        # 공개 API는 서버 밖 사용자를 나타내는 Object를 대상으로 받지 않는다 (그래서 HTTP 호출을 쓴다)
        try:
            await GuildChannel.set_permissions(real_channel, discord.Object(id=7, type=discord.User), overwrite=None)
            rejected = False
        except ValueError:
            rejected = True
        audit = StrayPermissionAudit(SimpleNamespace(user=SimpleNamespace(id=998)), FRepo([]))
        await audit._revoke(real_channel, 7, None)  # 서버를 떠난 사용자: HTTP 호출
        member = discord.User(state=SimpleNamespace(), data={"id": "8", "username": "x", "discriminator": "0",
                                                             "avatar": None, "global_name": None})
        await audit._revoke(real_channel, 8, member)  # 서버 멤버: 공개 set_permissions
        return rejected

    rejected = await attempt()
    check(rejected, "set_permissions는 Object 대상을 거부한다 (서버를 떠난 사용자에는 HTTP 호출이 필요)")
    check(calls == [(100, 7), (100, 8)], f"실제 discord.py 채널에서 두 경로 모두 delete_channel_permissions로 이어진다 {calls}")


def test_config_defaults():
    import subprocess

    def evaluate(env_value):
        environment = {**os.environ, "PLAYMATE_STRAY_REVOKE_ENABLED": env_value, "PLAYMATE_STAFF_ROLE_IDS": "11, 22,abc",
                       "PLAYMATE_PROTECTED_USER_IDS": "33"}
        result = subprocess.run(
            [sys.executable, "-c", "import config; print(config.STRAY_REVOKE_ENABLED, sorted(config.STRAY_STAFF_ROLE_IDS), "
                                   "sorted(config.STRAY_PROTECTED_USER_IDS), config.STRAY_WITHDRAWN_WINDOW_DAYS)"],
            cwd=ROOT, env=environment, capture_output=True, text=True)
        return result.stdout.strip().splitlines()[-1]

    check(evaluate("").startswith("False"), "환경변수가 없으면 dry-run")
    for value in ("false", "1", "yes", "on", "TRUE "[:-1] + "x"):
        check(evaluate(value).startswith("False"), f"'{value}'는 실제 회수를 켜지 않는다 (정확히 true만 켠다)")
    check(evaluate("true").startswith("True") and evaluate(" True ").startswith("True"), "true(대소문자/공백 허용)만 실제 회수를 켠다")
    check(evaluate("false").endswith("[11, 22] [33] 7"), "운영진 역할/보호 사용자 ID 파싱(숫자 아닌 값 무시), 탈퇴 근거 기간 기본 7일")

async def test_dry_run_log_once():
    import contextlib
    import io

    guild, channel, repo, audit = setup(BASE_ROWS, strays=(100000007777,))
    out = io.StringIO()
    with Mode(STRAY_REVOKE_ENABLED=False), contextlib.redirect_stdout(out):
        await run_at(audit, guild)
        await run_at(audit, guild, 301)
    text = out.getvalue()
    check(text.count("(dry-run) 회수 대상") == 1, "dry-run 로그는 같은 대상에 대해 반복하지 않는다")
    check("…7777" in text and "100000007777" not in text, "사용자 ID는 뒤 4자리만 로그에 남긴다")
    check(text.count("완료(dry-run)") == 2, "점검 요약은 매번 남는다")


# ------------------------------------------------------------------ 2부: 일회용 PostgreSQL
SCHEMA = """
DROP SCHEMA IF EXISTS bot_audit CASCADE;
CREATE SCHEMA bot_audit;
SET search_path = bot_audit;
CREATE TABLE members (member_id bigint PRIMARY KEY, discord_id varchar(30),
                      member_status varchar(20) NOT NULL DEFAULT 'ACTIVE', updated_at timestamp DEFAULT now());
CREATE UNIQUE INDEX uq_members_discord_id ON members (discord_id);
CREATE TABLE posts (post_id bigint PRIMARY KEY, title varchar(100) NOT NULL, post_status varchar(20));
CREATE TABLE recruits (recruit_id bigint PRIMARY KEY, post_id bigint NOT NULL UNIQUE REFERENCES posts(post_id),
                       recruit_mode varchar(20) NOT NULL, state varchar(20) NOT NULL, deadline_at timestamp,
                       regular_start_date date, meeting_start timestamp, meeting_end timestamp);
CREATE TABLE recruit_members (recruit_id bigint NOT NULL REFERENCES recruits(recruit_id),
                              member_id bigint NOT NULL REFERENCES members(member_id),
                              role varchar(20), status varchar(20), PRIMARY KEY (recruit_id, member_id));
CREATE TABLE recruit_discord_channels (
  recruit_id bigint NOT NULL PRIMARY KEY REFERENCES recruits(recruit_id),
  discord_category_id varchar(32) UNIQUE, discord_text_channel_id varchar(32) UNIQUE,
  discord_voice_channel_id varchar(32) UNIQUE,
  sync_status varchar(20) NOT NULL DEFAULT 'PENDING' CHECK (sync_status IN ('PENDING','SUCCESS','FAILED')),
  sync_error text, synced_at timestamptz, last_activity_at timestamptz, inactivity_warned_at timestamptz,
  scheduled_delete_at timestamptz, discord_deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
"""
DB_OPTIONS = "-c TimeZone=Asia/Seoul -c search_path=bot_audit"


def require_local_dsn():
    from psycopg.conninfo import conninfo_to_dict

    host = conninfo_to_dict(DSN).get("host")
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("일회용 로컬 DB(127.0.0.1/localhost/::1)에서만 실행합니다. 접속하지 않고 중단합니다.")


async def test_postgres():
    import psycopg

    from repositories.meeting_repository import PostgresMeetingRepository

    require_local_dsn()
    admin = psycopg.connect(DSN, autocommit=True)
    admin.execute(SCHEMA)
    connect = lambda: psycopg.connect(DSN, autocommit=True, options=DB_OPTIONS)  # noqa: E731
    conn = connect()
    # 모임 1: HOST(1) / 정상 참여자(3) / 참여 취소(4) / 곧 탈퇴할 참여자(2)
    conn.execute("INSERT INTO posts VALUES (1,'모임',NULL)")
    conn.execute("INSERT INTO recruits (recruit_id,post_id,recruit_mode,state,deadline_at) VALUES "
                 "(1,1,'regular','OPEN', now() - interval '1 hour')")
    for member_id in (1, 2, 3, 4):
        conn.execute("INSERT INTO members (member_id, discord_id) VALUES (%s,%s)", (member_id, str(1000 + member_id)))
    for member_id, role, status in ((1, "HOST", "JOINED"), (2, "MEMBER", "JOINED"), (3, "MEMBER", "JOINED"), (4, "MEMBER", "CANCELED")):
        conn.execute("INSERT INTO recruit_members VALUES (1,%s,%s,%s)", (member_id, role, status))
    conn.execute("INSERT INTO recruit_discord_channels (recruit_id, discord_text_channel_id, sync_status, last_activity_at) "
                 "VALUES (1,'100','SUCCESS', now())")

    guild = FGuild()
    channel = FChannel(100, 1)
    for user_id in (1001, 1002, 1003, 1004):
        channel.grant(user_id)  # 1004(참여 취소자)는 권한이 남은 상태
    guild.channels[100] = channel
    client = SimpleNamespace(get_guild=lambda guild_id: guild, user=SimpleNamespace(id=998))
    repo = PostgresMeetingRepository(connect)

    def sessions():
        return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()").fetchone()[0]

    def idle_in_tx():
        return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND "
                            "state LIKE 'idle in transaction%' AND pid<>pg_backend_pid()").fetchone()[0]

    def withdraw(member_id):
        """백엔드 withdraw_member와 같은 식별정보 비식별화 (discord_id를 'w<member_id>'로 바꾼다)."""
        conn.execute("UPDATE members SET discord_id = 'w' || member_id::text, member_status = 'WITHDRAWN', "
                     "updated_at = CURRENT_TIMESTAMP WHERE member_id = %s", (member_id,))

    # 탈퇴 전: 모두 자격자 또는 취소자라 대상이 없다
    audit = StrayPermissionAudit(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["candidates"] == 0 and summary["channels"] == 1, "탈퇴 전에는 잔여 권한 대상이 없다")

    withdraw(2)
    rows = repo.list_audit_rows()
    check(any(r["discord_id"] == "w2" and r["member_status"] == "WITHDRAWN" for r in rows),
          "탈퇴 회원은 discord_id가 'w<member_id>'로 조회된다 (참여자 동기화는 원래 ID를 알 수 없다)")
    check(all(s["discord_id"] != 1002 for s in repo.list_participant_states()),
          "일반 참여자 동기화의 대상에서도 빠진다 (그래서 Discord 쪽 overwrite를 직접 점검해야 한다)")

    # dry-run: 대상만 식별하고 변경 0회
    audit = StrayPermissionAudit(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=False):
        summary = await run_at(audit, guild)
    check(summary["candidates"] == 1 and summary["dry_run"] == 1 and channel.calls == [] and has(channel, 1002),
          "PostgreSQL 탈퇴 상태에서 dry-run: 대상 1명 식별, 변경 0회")

    # 실제 회수는 락/연결 없이: Discord 호출 중 Backend가 recruits 행을 수정해도 기다리지 않고 새 연결도 없다
    blocker_probe = {}

    async def probe_during_fetch():
        other = psycopg.connect(DSN, autocommit=True, options=DB_OPTIONS + " -c lock_timeout=500")
        try:
            other.execute("UPDATE recruits SET recruit_mode = recruit_mode WHERE recruit_id = 1")
            blocker_probe["immediate"] = True
        except psycopg.errors.LockNotAvailable:
            blocker_probe["immediate"] = False
        finally:
            other.close()
        blocker_probe["idle_in_tx"] = idle_in_tx()

    guild.on_fetch = probe_during_fetch
    sessions_before = sessions()
    audit = StrayPermissionAudit(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    guild.on_fetch = None
    check(summary["revoked"] == 1 and not has(channel, 1002), "실제 회수 모드: 탈퇴 회원의 권한 제거")
    check(has(channel, 1001) and has(channel, 1003), "정상 HOST와 참여자의 권한 유지")
    check(has(channel, 1004), "참여 취소자의 잔여 권한은 이 점검이 아니라 일반 동기화가 회수한다")
    check(blocker_probe == {"immediate": True, "idle_in_tx": 0}, "Discord 호출 중 recruits 행 락/열린 트랜잭션이 없다")
    check(sessions() <= sessions_before, "점검은 새 DB 연결을 만들지 않는다 (공유 연결 사용)")

    # DbSync.run_once 전체: 참여 취소자는 일반 동기화가, 탈퇴 회원은 점검이 처리하고 둘 다 멱등
    channel.grant(1002)  # 탈퇴 회원의 잔여 권한을 다시 만든다
    sync = db_sync_module.DbSync(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=True):
        await sync.run_once()
    check(not has(channel, 1002) and not any(k.id == 1004 and getattr(v, "send_messages", None) for k, v in channel.overwrites.items()),
          "run_once: 탈퇴 회원 권한 제거 + 참여 취소자 쓰기 권한 회수")
    check(has(channel, 1001) and has(channel, 1003), "run_once 후에도 HOST/정상 참여자 권한 유지")
    calls_before = len(channel.calls)
    with Mode(STRAY_REVOKE_ENABLED=True):
        await db_sync_module.DbSync(client, repo).run_once()  # 재시작
    check(len(channel.calls) == calls_before, "재시작 후 반복 실행해도 추가 변경 없음 (멱등)")

    # 회수 직전에 상태가 바뀜: 같은 Discord 계정이 새 회원으로 가입해 참여 (탈퇴 회원의 ID와 같은 ID)
    channel.grant(1002)

    async def rejoin_during_fetch():
        conn.execute("INSERT INTO members (member_id, discord_id) VALUES (9, '1002') ON CONFLICT DO NOTHING")
        conn.execute("INSERT INTO recruit_members VALUES (1,9,'MEMBER','JOINED') ON CONFLICT DO NOTHING")

    guild.on_fetch = rejoin_during_fetch
    audit = StrayPermissionAudit(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    guild.on_fetch = None
    check(summary["revoked"] == 0 and has(channel, 1002), "회수 직전에 참여자가 된 사용자는 회수하지 않는다 (PostgreSQL)")

    # DB 조회가 실패하면 run_once는 계속 진행하고 아무것도 회수하지 않는다
    channel.grant(7777)
    original = repo.list_audit_rows
    repo.list_audit_rows = lambda recruit_id=None: (_ for _ in ()).throw(RuntimeError("db down"))
    calls_before = len(channel.calls)
    with Mode(STRAY_REVOKE_ENABLED=True):
        await db_sync_module.DbSync(client, repo).run_once()
    repo.list_audit_rows = original
    check(len(channel.calls) == calls_before and has(channel, 7777), "점검용 DB 조회 실패: 회수하지 않고 동기화는 계속")

    # 모든 참여자 행이 사라진 듯 보이는 불완전한 조회(자격자 0명)도 회수하지 않는다
    conn.execute("UPDATE recruit_members SET status='CANCELED' WHERE recruit_id=1")
    audit = StrayPermissionAudit(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and summary["skipped_channels"] == 1 and has(channel, 7777),
          "자격자가 한 명도 없는 조회 결과로는 회수하지 않는다 (PostgreSQL)")
    # 탈퇴한 지 기간이 지난 회원은 근거가 아니다 (PostgreSQL): 오래 뒤에 남은 overwrite는 수동 확인 대상
    conn.execute("UPDATE recruit_members SET status='JOINED' WHERE recruit_id=1")
    conn.execute("UPDATE members SET updated_at = now() - interval '30 days' WHERE member_id = 2")
    channel.grant(7777)
    audit = StrayPermissionAudit(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 0 and has(channel, 7777), "탈퇴한 지 30일 지난 기록은 회수 근거가 아니다 (PostgreSQL)")
    conn.execute("UPDATE members SET updated_at = now() WHERE member_id = 2")
    audit = StrayPermissionAudit(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=True):
        summary = await run_at(audit, guild)
    check(summary["revoked"] == 1 and not has(channel, 7777), "탈퇴 직후(기간 안)에는 같은 overwrite가 회수 대상이다 (PostgreSQL)")

    # DB 스키마가 기대와 다르면(member_status 컬럼 누락 등) 회수하지 않고 안전하게 끝낸다
    channel.grant(7777)
    conn.execute("ALTER TABLE members DROP COLUMN member_status")
    calls_before = len(channel.calls)
    with Mode(STRAY_REVOKE_ENABLED=True):
        await db_sync_module.DbSync(client, repo).run_once()
    check(not any(call[0] == 7777 for call in channel.calls[calls_before:]) and has(channel, 7777),
          "member_status 컬럼이 없으면 점검 실패로 끝나고(run_once는 계속) 잔여 권한을 회수하지 않는다")
    audit = StrayPermissionAudit(client, repo)
    with Mode(STRAY_REVOKE_ENABLED=True):
        try:
            await run_at(audit, guild)
            raised = False
        except psycopg.errors.UndefinedColumn:
            raised = True
    check(raised and has(channel, 7777), "점검은 DB 오류를 예외로 올리고 권한은 그대로 둔다 (run_once가 격리)")
    conn.close()
    admin.execute("DROP SCHEMA IF EXISTS bot_audit CASCADE")
    admin.close()


async def main():
    test_classify()
    await test_detect_and_modes()
    await test_protection()
    await test_incomplete_and_identification()
    await test_recheck_before_revoke()
    await test_discord_errors()
    await test_manual_staff_protection()
    await test_dry_run_never_writes()
    await test_discord_py_compat()
    test_config_defaults()
    await test_dry_run_log_once()
    if DSN:
        await test_postgres()
    else:
        print("PLAYMATE_TEST_PG_DSN이 없어 PostgreSQL 부분은 건너뜁니다.")
    check(config.STRAY_REVOKE_ENABLED is False, "기본값은 dry-run (환경변수로 명시하지 않으면 실제 회수하지 않는다)")
    print(f"PASS: {checks} stray permission audit assertions passed.")


asyncio.run(main())
