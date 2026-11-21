"""Discord REST 오류 분류.

두 가지 속성으로 호출 측의 행동이 갈린다 (HTTP 상태만으로는 구분할 수 없는 정보다).

retryable        나중에 같은 요청을 다시 시도해 볼 가치가 있는가 (429, 5xx, 타임아웃, 네트워크 오류).
outcome_unknown  요청이 Discord에서 실행되었을 수도 있는가 (부작용이 있는 요청의 5xx/타임아웃).
                 True면 호출 측은 "다시 보내기" 전에 먼저 결과를 확인(조정)해야 한다. 그대로 다시 보내면
                 메시지가 두 번 가거나 채널이 두 개 생길 수 있다.

401/403/404/기타 4xx는 같은 요청을 다시 보내도 결과가 같으므로 retryable=False다.
"""
import re

_LONG_ID = re.compile(r"\d{15,}")


def mask_ids(text: str) -> str:
    """로그와 오류 메시지에 남는 Discord ID(snowflake)를 뒤 4자리만 남기고 가린다."""
    return _LONG_ID.sub(lambda match: "…" + match.group()[-4:], text)


class DiscordError(Exception):
    retryable = False

    def __init__(self, message: str, *, status: int | None = None, code: int | None = None,
                 method: str | None = None, route: str | None = None,
                 retry_after: float | None = None, outcome_unknown: bool = False):
        self.status = status
        self.code = code  # Discord JSON 오류 코드 (예: 50007 = DM을 보낼 수 없는 사용자)
        self.method = method
        self.route = route
        self.retry_after = retry_after
        self.outcome_unknown = outcome_unknown
        super().__init__(message)


class DiscordAuthError(DiscordError):
    """401: 토큰이 없거나 잘못됨. 재시도해도 같다 (반복하면 Discord가 IP를 일시 차단할 수 있다)."""


class DiscordForbidden(DiscordError):
    """403: 봇에 권한이 없거나 DM이 막혀 있음."""

    @property
    def is_dm_blocked(self) -> bool:
        return self.code == 50007  # Cannot send messages to this user


class DiscordNotFound(DiscordError):
    """404: 채널, 사용자, 메시지가 없음."""


class DiscordRequestError(DiscordError):
    """400 등 그 밖의 4xx: 요청 형식 오류. 코드 버그이므로 재시도하지 않는다."""


class DiscordRateLimited(DiscordError):
    """429: 재시도 횟수를 다 썼거나 Retry-After가 허용 대기 시간을 넘음. 요청은 실행되지 않았다."""
    retryable = True


class DiscordServerError(DiscordError):
    """5xx: Discord 쪽 일시 오류."""
    retryable = True


class DiscordTimeoutError(DiscordError):
    """응답을 받기 전에 시간이 초과됨. 요청이 이미 전달되었을 수 있다."""
    retryable = True


class DiscordNetworkError(DiscordError):
    """연결 실패 등. 연결 자체가 안 된 경우(outcome_unknown=False)와 중간에 끊긴 경우를 구분한다."""
    retryable = True


class DiscordResponseError(DiscordError):
    """2xx인데 본문을 해석할 수 없음."""
