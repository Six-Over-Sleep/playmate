"""입력 검증 보안 회귀 테스트(Issue #82 F3·F6·업로드 응답 헤더).

- F3: 회원가입·마이페이지 닉네임 길이·예약어 정책 통일
- F6: 사용자가 저장하는 외부 링크(purchase_url)는 http·https만 허용
- 업로드 정적 파일 응답의 X-Content-Type-Options: nosniff
DB와 외부 서비스에는 접속하지 않는다.
"""

import asyncio
import sys
from contextlib import contextmanager
from io import BytesIO

import pytest
from fastapi import UploadFile
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.routing import Mount

from app.core import uploads
from backend.app.schemas.member import MemberSignup
from backend.app.schemas.mypage import MyProfileUpdate
from backend.app.schemas.recruit import RecruitUpdate, validate_external_url

PNG = b"\x89PNG\r\n\x1a\nexample"
SIGNUP = {"cohort": 1, "track": "data-ml"}

REJECTED_NICKNAMES = [
    "a",  # 2자 미만
    "가" * 21,  # 20자 초과
    "   ",  # 공백만
    "관리자",
    " 관 리 자 ",  # 공백을 넣은 예약어
    "Admin",  # 대소문자 무시
    "탈퇴한 사용자",
    "익명",
    "PlayMate",
]


@pytest.mark.parametrize("nickname", REJECTED_NICKNAMES)
def test_signup_and_profile_reject_same_nicknames(nickname):
    """회원가입과 마이페이지 변경이 같은 닉네임을 똑같이 거부한다."""
    with pytest.raises(ValidationError):
        MemberSignup(nickname=nickname, **SIGNUP)
    with pytest.raises(ValidationError):
        MyProfileUpdate(nickname=nickname)


@pytest.mark.parametrize("nickname", ["민혁", "  플레이메이트러버  ", "가" * 20, "admin_kim"])
def test_signup_and_profile_accept_same_nicknames(nickname):
    """정상 닉네임은 두 경로 모두 앞뒤 공백만 제거하고 허용한다."""
    assert MemberSignup(nickname=nickname, **SIGNUP).nickname == nickname.strip()
    assert MyProfileUpdate(nickname=nickname).nickname == nickname.strip()


@contextmanager
def fake_profile_cursor(saved):
    """닉네임 변경 UPDATE 파라미터를 기록하고 갱신된 행을 돌려주는 대역."""

    class Cursor:
        def execute(self, sql, params):
            saved.append(params)

        def fetchone(self):
            return {"member_id": 1, "nickname": saved[-1][0], "profile_image_url": None}

    yield Cursor()


def test_profile_nickname_api_applies_policy(client, monkeypatch):
    """마이페이지 닉네임 변경 API: 정책 위반은 422로 DB에 닿지 않고, 정상 값은 저장된다."""
    from app.main import app
    from backend.app.core.auth import get_current_member_id as router_auth

    mypage = sys.modules["backend.app.routers.mypage"]
    # mypage 라우터는 backend.app.core.auth 경로의 인증 함수를 쓰므로 그 함수도 회원 1로 대체한다.
    monkeypatch.setitem(app.dependency_overrides, router_auth, lambda: 1)
    saved = []
    monkeypatch.setattr(mypage, "db_cursor", lambda **kwargs: fake_profile_cursor(saved))

    assert client.patch("/api/mypage/profile", json={"nickname": "가" * 21}).status_code == 422
    assert client.patch("/api/mypage/profile", json={"nickname": "관리자"}).status_code == 422
    assert saved == []

    response = client.patch("/api/mypage/profile", json={"nickname": "  새닉네임  "})
    assert response.status_code == 200
    assert response.json()["nickname"] == "새닉네임"
    assert saved == [("새닉네임", 1)]


def test_signup_api_rejects_reserved_nickname_before_session_check(client):
    """회원가입 API는 예약 닉네임을 입력 검증 단계(422)에서 거부한다."""
    response = client.post("/auth/signup", json={"nickname": "운영자", **SIGNUP})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(document.cookie)",
        "JaVaScRiPt:alert(1)",
        "  javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        "//evil.example/path",  # 스킴 없음
        "https:///no-host",
        "http://exa mple.com",  # 공백 포함
        "https://example.com/\nset-cookie",
        "ftp://example.com/file",
        "https://example.com/" + "a" * 2050,
    ],
)
def test_external_url_rejects_unsafe_values(url):
    """http·https가 아닌 스킴, 호스트 없는 주소, 공백·제어문자, 과도한 길이를 거부한다."""
    with pytest.raises(ValueError):
        validate_external_url(url)
    with pytest.raises(ValidationError):
        RecruitUpdate(purchase_url=url)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://shop.example.com/item?id=1&ref=pm", "https://shop.example.com/item?id=1&ref=pm"),
        ("  http://example.com/path  ", "http://example.com/path"),
        ("HTTPS://EXAMPLE.COM", "HTTPS://EXAMPLE.COM"),
        ("", None),
        (None, None),
    ],
)
def test_external_url_keeps_normal_links(url, expected):
    """정상 http·https 링크는 유지하고, 빈 값은 링크 없음(None)으로 저장한다."""
    assert validate_external_url(url) == expected
    assert RecruitUpdate(purchase_url=url).purchase_url == expected


def test_uploaded_file_response_has_nosniff(client, tmp_path, monkeypatch):
    """업로드 정적 파일 응답에 nosniff가 붙어 브라우저가 형식을 추측하지 않는다."""
    from app.main import app

    monkeypatch.setattr(uploads, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path / "uploads" / "posts")
    image = UploadFile(BytesIO(PNG), filename="t.png", headers=Headers({"content-type": "image/png"}))
    saved = asyncio.run(uploads.save_images([image]))
    static = next(r.app for r in app.routes if isinstance(r, Mount) and r.path == "/uploads")
    monkeypatch.setattr(static, "directory", str(tmp_path / "uploads"))
    monkeypatch.setattr(static, "all_directories", [str(tmp_path / "uploads")])

    response = client.get("/uploads/" + saved[0]["stored_name"])

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"] == "image/png"
