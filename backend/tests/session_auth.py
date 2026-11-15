"""통합 테스트용 로그인 세션 쿠키(테스트 수집 대상 아님).

develop에서 개발용 X-Dev-Member-ID 인증을 없앴으므로, 실제 앱과 같은 경로
(서명된 playmate_session 쿠키 → members의 discord_id·member_status 확인)로 인증한다.
서명 키는 conftest.py가 강제로 넣는 테스트 전용 SESSION_SECRET_KEY다.
"""

import json
import os
from base64 import b64encode

from itsdangerous import TimestampSigner


def session_headers(member_id: int, discord_id: str) -> dict[str, str]:
    """요청마다 넘기는 Cookie 헤더. TestClient는 응답 쿠키를 저장하므로 호출 전 client.cookies.clear()를 함께 쓴다."""
    data = {"member_id": member_id, "user": {"discord_id": str(discord_id)}}
    signed = TimestampSigner(os.environ["SESSION_SECRET_KEY"]).sign(
        b64encode(json.dumps(data).encode())
    ).decode()
    return {"Cookie": "playmate_session=" + signed}
