"""Discord REST API v10 공통 클라이언트 (Gateway, discord.py, 서버 캐시 없이 동작한다).

Lambda 같은 짧은 실행 환경에서 쓰려고 동기 방식이며 표준 라이브러리만 쓴다. 토큰은 생성자로만 받고
환경변수나 config를 읽지 않는다 (호출하는 Lambda 핸들러가 시크릿을 읽어 넘긴다).

재시도 원칙 (이 파일에서 가장 중요한 규칙):
  * 429  : 요청이 실행되지 않았으므로 모든 요청을 Retry-After만큼 기다렸다가 다시 보낸다.
           Retry-After가 max_retry_after를 넘으면 기다리지 않고 DiscordRateLimited를 올린다.
  * 연결 자체가 실패(연결 거부/DNS): 요청이 전달되지 않았으므로 모든 요청을 재시도한다.
  * 5xx, 타임아웃, 중간에 끊김:
      - 멱등 요청(GET, PUT 권한, DELETE, DM 채널 열기)은 backoff 후 재시도한다.
      - 부작용 요청(메시지 전송, 채널 생성)은 **재시도하지 않는다.** 실행되었을 수도 있어서, 다시 보내면
        메시지가 두 번 가거나 채널이 두 개 생길 수 있다. DiscordError.outcome_unknown=True로 알리고
        호출 측이 결과를 확인(예: 최근 메시지 / 채널 주제로 조회)한 뒤 결정한다.
  * 401/403/404/400 등 4xx: 재시도하지 않는다.
"""
import json
import logging
import time
import urllib.parse
from typing import Any, Callable

from discord_rest.errors import (
    DiscordAuthError,
    DiscordError,
    DiscordForbidden,
    DiscordNetworkError,
    DiscordNotFound,
    DiscordRateLimited,
    DiscordRequestError,
    DiscordResponseError,
    DiscordServerError,
    DiscordTimeoutError,
    mask_ids,
)
from discord_rest.permissions import OVERWRITE_MEMBER, overwrite
from discord_rest.transport import TransportError, TransportTimeout, urllib_transport

API_BASE = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/Six-Over-Sleep/playmate, 0.1)"
CHANNEL_TYPE_TEXT = 0
MESSAGE_CONTENT_LIMIT = 2000
MAX_EMBEDS = 10
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
log = logging.getLogger("playmate.discord_rest")


def _snowflake(value: Any, name: str) -> str:
    """경로에 들어가는 ID를 양의 정수 문자열로 검증한다 (경로 조작 방지)."""
    if isinstance(value, bool):
        raise ValueError(f"{name}은 양의 정수여야 합니다.")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{name}은 양의 정수여야 합니다.") from None
    if number <= 0:
        raise ValueError(f"{name}은 양의 정수여야 합니다.")
    return str(number)


def _check_base_url(base_url: str) -> str:
    """운영은 https만 허용한다. 테스트용 가짜 서버는 loopback http만 허용한다 (토큰이 평문으로 나가지 않게)."""
    parsed = urllib.parse.urlsplit(base_url)
    loopback = parsed.scheme == "http" and (parsed.hostname or "") in [h.strip("[]") for h in LOOPBACK_HOSTS]
    if parsed.scheme != "https" and not loopback:
        raise ValueError("base_url은 https(또는 테스트용 loopback http)여야 합니다.")
    return base_url.rstrip("/")


class DiscordRestClient:
    def __init__(self, token: str, *, base_url: str = API_BASE,
                 transport: Callable | None = None, timeout: float = 10.0,
                 max_retries: int = 3, backoff_base: float = 0.5, max_backoff: float = 8.0,
                 max_retry_after: float = 30.0, time_budget: float | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        if not isinstance(token, str) or not token.strip() or any(c.isspace() for c in token):
            raise ValueError("Discord 토큰이 비어 있거나 공백을 포함합니다.")  # 값은 오류에 넣지 않는다
        self._token = token
        self._base = _check_base_url(base_url)
        self._transport = transport or urllib_transport
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base, self._max_backoff = backoff_base, max_backoff
        self._max_retry_after = max_retry_after
        self._time_budget = time_budget  # Lambda 제한시간 안에서 재시도를 멈추기 위한 총 예산(초)
        self._sleep, self._clock = sleep, clock

    def __repr__(self) -> str:  # 토큰이 로그나 traceback에 찍히지 않게 한다
        return f"<DiscordRestClient base={self._base!r} token=***>"

    # -- 공통 요청 -----------------------------------------------------------------
    def _request(self, method: str, path: str, *, body: Any = None, query: dict | None = None,
                 idempotent: bool, reason: str | None = None) -> Any:
        url = self._base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Authorization": f"Bot {self._token}", "User-Agent": USER_AGENT, "Accept": "application/json"}
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if reason:
            headers["X-Audit-Log-Reason"] = urllib.parse.quote(reason, safe="")
        route = mask_ids(f"{method} {path}")
        started = self._clock()
        attempt = 0
        while True:
            last = attempt >= self._max_retries
            try:
                status, response_headers, raw = self._transport(method, url, headers, payload, self._timeout)
            except TransportTimeout:
                error = DiscordTimeoutError(f"응답 시간 초과: {route}", method=method, route=route,
                                            outcome_unknown=not idempotent)
                if not idempotent or last or self._out_of_budget(started, self._backoff(attempt)):
                    self._log_failure(error)
                    raise error from None
                attempt = self._wait(attempt, self._backoff(attempt), route, "timeout")
                continue
            except TransportError as failure:
                sent = failure.maybe_sent
                error = DiscordNetworkError(f"연결 오류: {route} ({failure})", method=method, route=route,
                                            outcome_unknown=sent and not idempotent)
                if (sent and not idempotent) or last or self._out_of_budget(started, self._backoff(attempt)):
                    self._log_failure(error)
                    raise error from None
                attempt = self._wait(attempt, self._backoff(attempt), route, "network")
                continue

            if 200 <= status < 300:
                return self._parse_success(status, raw, method, route, idempotent)

            data = self._parse_error_body(raw)
            code = data.get("code") if isinstance(data.get("code"), int) else None
            message = str(data.get("message") or "")[:200]

            if status == 429:
                retry_after = self._retry_after(data, response_headers)
                error = DiscordRateLimited(f"Rate limit: {route} (retry_after={retry_after}s)", status=429,
                                           code=code, method=method, route=route, retry_after=retry_after)
                if retry_after > self._max_retry_after or last or self._out_of_budget(started, retry_after):
                    self._log_failure(error)
                    raise error
                attempt = self._wait(attempt, retry_after, route, "429")
                continue
            if status >= 500:
                error = DiscordServerError(f"Discord 서버 오류 {status}: {route}", status=status, code=code,
                                           method=method, route=route, outcome_unknown=not idempotent)
                if not idempotent or last or self._out_of_budget(started, self._backoff(attempt)):
                    self._log_failure(error)
                    raise error
                attempt = self._wait(attempt, self._backoff(attempt), route, str(status))
                continue

            kind = {401: DiscordAuthError, 403: DiscordForbidden, 404: DiscordNotFound}.get(status, DiscordRequestError)
            error = kind(f"Discord {status}{'' if code is None else f' (code {code})'}: {route} {mask_ids(message)}".rstrip(),
                         status=status, code=code, method=method, route=route)
            self._log_failure(error)
            raise error

    def _backoff(self, attempt: int) -> float:
        return min(self._backoff_base * (2 ** attempt), self._max_backoff)

    def _out_of_budget(self, started: float, next_wait: float) -> bool:
        return self._time_budget is not None and (self._clock() - started) + next_wait >= self._time_budget

    def _wait(self, attempt: int, seconds: float, route: str, why: str) -> int:
        log.warning("재시도 %s (%s) %.1f초 후, %d/%d", route, why, seconds, attempt + 1, self._max_retries)
        self._sleep(seconds)
        return attempt + 1

    @staticmethod
    def _log_failure(error: DiscordError) -> None:
        log.warning("Discord 요청 실패 %s: %s outcome_unknown=%s", error.route, type(error).__name__,
                    error.outcome_unknown)

    @staticmethod
    def _parse_error_body(raw: bytes) -> dict:
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _retry_after(data: dict, headers: dict) -> float:
        for value in (data.get("retry_after"), headers.get("retry-after")):
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                continue
            if seconds >= 0:
                return seconds
        return 1.0

    @staticmethod
    def _parse_success(status: int, raw: bytes, method: str, route: str, idempotent: bool):
        if status == 204 or not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise DiscordResponseError(f"응답을 해석할 수 없음: {route}", status=status, method=method, route=route,
                                       outcome_unknown=not idempotent) from None

    # -- 채널 조회 ------------------------------------------------------------------
    def list_guild_channels(self, guild_id: int) -> list[dict]:
        """GET /guilds/{id}/channels: 서버의 모든 채널 (캐시 대신 매번 조회한다)."""
        return self._request("GET", f"/guilds/{_snowflake(guild_id, 'guild_id')}/channels", idempotent=True)

    def get_channel(self, channel_id: int) -> dict:
        """GET /channels/{id}: 채널 정보 (type, topic, parent_id, permission_overwrites 포함)."""
        return self._request("GET", f"/channels/{_snowflake(channel_id, 'channel_id')}", idempotent=True)

    def get_guild_member(self, guild_id: int, user_id: int) -> dict:
        """GET /guilds/{id}/members/{id}: 서버에 있는 사용자인지 확인 (없으면 DiscordNotFound)."""
        return self._request("GET", f"/guilds/{_snowflake(guild_id, 'guild_id')}/members/{_snowflake(user_id, 'user_id')}",
                             idempotent=True)

    # -- 메시지 ---------------------------------------------------------------------
    def send_message(self, channel_id: int, *, content: str | None = None, embeds: list[dict] | None = None,
                     allowed_mentions: dict | None = None, nonce: str | None = None) -> dict:
        """POST /channels/{id}/messages. **자동 재시도하지 않는 부작용 요청** (429/연결 실패만 재시도).

        allowed_mentions 기본값은 멘션 없음({"parse": []})이다 (기존 공지의 AllowedMentions.none()과 같다).
        nonce는 Discord가 같은 nonce의 중복 전송을 막는 데 쓸 수 있는 값이다 (enforce_nonce로 요청).
        그 보장은 이 PoC에서 실제 Discord로 검증하지 않았으므로 중복 방지의 유일한 수단으로 믿지 말 것.
        """
        if not content and not embeds:
            raise ValueError("content 또는 embeds가 필요합니다.")
        if content is not None and len(content) > MESSAGE_CONTENT_LIMIT:
            raise ValueError(f"content는 {MESSAGE_CONTENT_LIMIT}자 이하여야 합니다.")
        if embeds is not None and len(embeds) > MAX_EMBEDS:
            raise ValueError(f"embeds는 {MAX_EMBEDS}개 이하여야 합니다.")
        body: dict[str, Any] = {"allowed_mentions": allowed_mentions if allowed_mentions is not None else {"parse": []}}
        if content:
            body["content"] = content
        if embeds:
            body["embeds"] = embeds
        if nonce:
            body["nonce"], body["enforce_nonce"] = str(nonce)[:25], True
        return self._request("POST", f"/channels/{_snowflake(channel_id, 'channel_id')}/messages", body=body,
                             idempotent=False)

    def get_recent_messages(self, channel_id: int, limit: int = 50, *, before: int | None = None,
                            after: int | None = None) -> list[dict]:
        """GET /channels/{id}/messages: 최신순 최근 메시지 (limit 1~100). 비활성 판정과 중복 전송 확인에 쓴다."""
        if not 1 <= int(limit) <= 100:
            raise ValueError("limit은 1~100이어야 합니다.")
        query: dict[str, Any] = {"limit": int(limit)}
        if before is not None:
            query["before"] = _snowflake(before, "before")
        if after is not None:
            query["after"] = _snowflake(after, "after")
        return self._request("GET", f"/channels/{_snowflake(channel_id, 'channel_id')}/messages", query=query,
                             idempotent=True)

    # -- DM -------------------------------------------------------------------------
    def create_dm_channel(self, user_id: int) -> dict:
        """POST /users/@me/channels: DM 채널 열기. 이미 있으면 같은 채널을 돌려주므로 멱등이라 재시도한다."""
        return self._request("POST", "/users/@me/channels", body={"recipient_id": _snowflake(user_id, "user_id")},
                             idempotent=True)

    def send_dm(self, user_id: int, *, content: str | None = None, embeds: list[dict] | None = None,
                nonce: str | None = None) -> dict:
        """DM 채널을 열고 메시지를 보낸다. 사용자 DM 차단은 DiscordForbidden.is_dm_blocked(코드 50007)로 구분한다."""
        channel = self.create_dm_channel(user_id)
        return self.send_message(channel["id"], content=content, embeds=embeds, nonce=nonce)

    # -- 채널 생성 / 삭제 -----------------------------------------------------------
    def create_guild_channel(self, guild_id: int, *, name: str, channel_type: int = CHANNEL_TYPE_TEXT,
                             parent_id: int | None = None, topic: str | None = None,
                             permission_overwrites: list[dict] | None = None, reason: str | None = None) -> dict:
        """POST /guilds/{id}/channels. **자동 재시도하지 않는 부작용 요청.**

        5xx/타임아웃이면 채널이 만들어졌을 수 있다 (DiscordError.outcome_unknown=True). 호출 측은
        list_guild_channels로 같은 topic(모임 표지)의 채널이 있는지 먼저 확인한 뒤 다시 만들지 정해야 한다.
        """
        name = (name or "").strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("채널 이름은 1~100자여야 합니다.")
        body: dict[str, Any] = {"name": name, "type": channel_type}
        if parent_id is not None:
            body["parent_id"] = _snowflake(parent_id, "parent_id")
        if topic is not None:
            body["topic"] = topic[:1024]
        if permission_overwrites:
            body["permission_overwrites"] = permission_overwrites
        return self._request("POST", f"/guilds/{_snowflake(guild_id, 'guild_id')}/channels", body=body,
                             idempotent=False, reason=reason)

    def delete_channel(self, channel_id: int, *, reason: str | None = None, missing_ok: bool = False) -> bool:
        """DELETE /channels/{id}: 멱등이라 5xx/타임아웃은 재시도한다. missing_ok면 404를 '이미 삭제됨'(False)으로 본다.

        이 함수는 어떤 채널이든 지울 수 있다. 모임 채널 삭제에는 안전 확인을 하는 reuse.safe_delete_meeting_channel을 쓴다.
        """
        try:
            self._request("DELETE", f"/channels/{_snowflake(channel_id, 'channel_id')}", idempotent=True, reason=reason)
        except DiscordNotFound:
            if not missing_ok:
                raise
            return False
        return True

    # -- 채널별 사용자 권한 ------------------------------------------------------------
    def get_member_overwrite(self, channel_id: int, user_id: int) -> dict | None:
        """채널의 개별 사용자 overwrite({"id","type","allow","deny"})를 돌려준다. 없으면 None."""
        user = _snowflake(user_id, "user_id")
        for entry in self.get_channel(channel_id).get("permission_overwrites") or []:
            if entry.get("type") == OVERWRITE_MEMBER and str(entry.get("id")) == user:
                return entry
        return None

    def set_member_permissions(self, channel_id: int, user_id: int, *, allow: int, deny: int,
                               reason: str | None = None) -> None:
        """PUT /channels/{id}/permissions/{user}: 같은 값을 다시 설정해도 결과가 같아 멱등이다 (재시도함)."""
        user = _snowflake(user_id, "user_id")
        body = overwrite(int(user), OVERWRITE_MEMBER, allow, deny)
        self._request("PUT", f"/channels/{_snowflake(channel_id, 'channel_id')}/permissions/{user}",
                      body={"type": body["type"], "allow": body["allow"], "deny": body["deny"]},
                      idempotent=True, reason=reason)

    def clear_member_permissions(self, channel_id: int, user_id: int, *, reason: str | None = None) -> bool:
        """DELETE /channels/{id}/permissions/{user}: 개별 overwrite 삭제 (이미 없으면 False)."""
        try:
            self._request("DELETE",
                          f"/channels/{_snowflake(channel_id, 'channel_id')}/permissions/{_snowflake(user_id, 'user_id')}",
                          idempotent=True, reason=reason)
        except DiscordNotFound:
            return False
        return True
