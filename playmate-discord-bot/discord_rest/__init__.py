"""Discord REST API v10 클라이언트와 Lambda 전환용 순수 로직.

이 패키지의 client / errors / transport / permissions / inactivity는 discord.py, config, DB를 import하지 않는다.
기존 Gateway Bot 코드를 재사용하는 어댑터는 `discord_rest.reuse`에 따로 있고, 그것만 기존 모듈을 import한다.
"""
from discord_rest.client import (
    API_BASE,
    DELETE_ALREADY_GONE,
    DELETE_DELETED,
    DELETE_GONE_AFTER_RETRY,
    DiscordRestClient,
)
from discord_rest.errors import (
    DiscordAuthError,
    DiscordError,
    DiscordForbidden,
    DiscordNetworkError,
    DiscordNotFound,
    DiscordRateLimited,
    DiscordRedirectError,
    DiscordRequestError,
    DiscordResponseError,
    DiscordServerError,
    DiscordTimeoutError,
)

__all__ = [
    "API_BASE", "DiscordRestClient", "DELETE_DELETED", "DELETE_ALREADY_GONE", "DELETE_GONE_AFTER_RETRY",
    "DiscordError", "DiscordAuthError", "DiscordForbidden", "DiscordNotFound", "DiscordRedirectError",
    "DiscordRequestError", "DiscordRateLimited", "DiscordServerError", "DiscordTimeoutError",
    "DiscordNetworkError", "DiscordResponseError",
]
