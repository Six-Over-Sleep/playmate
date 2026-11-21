"""HTTP 전송 계층 (표준 라이브러리만 사용). 테스트에서는 이 함수를 가짜로 바꿀 수 있다.

transport(method, url, headers, body, timeout) -> (status, 소문자 헤더 dict, 본문 bytes)
HTTP 오류 상태(4xx/5xx)는 예외가 아니라 정상 반환값이다. 연결/시간 초과만 예외로 올린다.
오류 메시지에는 URL, 헤더(토큰)를 넣지 않고 예외 종류만 남긴다.
"""
import http.client
import socket
import urllib.error
import urllib.request


class TransportTimeout(Exception):
    """응답을 기다리다 시간이 초과됨. 요청이 서버에 전달되었을 수 있다."""
    maybe_sent = True


class TransportError(Exception):
    """연결 오류. maybe_sent=False면 요청이 서버에 전달되지 않은 것이 확실하다 (연결 거부, DNS 실패)."""

    def __init__(self, message: str, maybe_sent: bool):
        self.maybe_sent = maybe_sent
        super().__init__(message)


def _never_sent(reason) -> bool:
    return isinstance(reason, (ConnectionRefusedError, socket.gaierror))


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        try:
            payload = error.read()
        finally:
            error.close()
        return error.code, {k.lower(): v for k, v in error.headers.items()}, payload
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise TransportTimeout("timeout") from None
        raise TransportError(f"connection error: {type(reason).__name__}", maybe_sent=not _never_sent(reason)) from None
    except (TimeoutError, socket.timeout):
        raise TransportTimeout("timeout") from None
    except (http.client.HTTPException, OSError) as error:
        raise TransportError(f"connection error: {type(error).__name__}", maybe_sent=True) from None
