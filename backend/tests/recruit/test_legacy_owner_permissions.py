"""모임 수정·삭제 권한 회귀 테스트(Issue #82, PR #90).

실제 main 앱 라우트를 격리 SQLite와 가짜 인증(runtime fixture)으로 호출한다.
공용 DB·Discord에는 접속하지 않는다. 회원 1은 작성자, 2는 일반 회원, 9는 ADMIN 역할이다.
"""

import pytest

from backend.tests.recruit.test_runtime_api import json_payload, runtime  # noqa: F401

LEGACY_CATEGORIES = [
    ("sports", {"sport_name": "러닝"}),
    ("game", {"game_name": "보드게임"}),
    ("group_buy", {"product_name": "책"}),
    ("study", {"study_topic": "기존 스터디"}),
]


def create_legacy(runtime, payload, category="sports", extra=None):
    """로그인 세션(회원 1)으로 기존 모임을 만들고 모임 ID를 반환한다."""
    body = {
        "title": "원래 제목",
        "body": "원래 본문",
        "category": category,
        "recruit_mode": "short",
        "capacity": 6,
        "deadline_at": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_start": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_end": payload["ends_at"].replace(tzinfo=None).isoformat(),
        **(extra or {"sport_name": "러닝"}),
    }
    created = runtime.request("POST", "/api/recruits", json=body, legacy_login=True)
    assert created.status_code == 201, created.text
    recruit_id = created.json()["recruit_id"]
    # 신규 프로그램이 아닌 기존 모임 경로인지 확인한다.
    assert "lifecycle_status" not in runtime.request("GET", f"/api/recruits/{recruit_id}").json()
    return recruit_id


def snapshot(runtime, recruit_id):
    """상세 조회 상태와 주요 필드를 비교용으로 반환한다."""
    response = runtime.request("GET", f"/api/recruits/{recruit_id}")
    if response.status_code != 200:
        return response.status_code, None
    data = response.json()
    return 200, {key: data.get(key) for key in ("title", "body", "capacity", "category")}


@pytest.mark.parametrize(
    "actor,expected",
    [(None, 401), (2, 403), (9, 403)],
    ids=["anonymous", "other_member", "admin"],  # 비로그인·다른 회원·ADMIN 역할
)
def test_legacy_edit_and_delete_rejected_without_change(runtime, payload, actor, expected):
    """작성자가 아니면 수정·삭제가 거부되고 데이터가 바뀌지 않는다.

    현재 정책상 ADMIN 역할도 다른 회원의 기존 모임을 수정·삭제할 수 없다.
    """
    recruit_id = create_legacy(runtime, payload)
    before = snapshot(runtime, recruit_id)

    edit = runtime.request("PATCH", f"/api/recruits/{recruit_id}", json={"title": "변조"}, member=actor)
    delete = runtime.request("DELETE", f"/api/recruits/{recruit_id}", member=actor)

    assert (edit.status_code, delete.status_code) == (expected, expected), (edit.text, delete.text)
    assert snapshot(runtime, recruit_id) == before


@pytest.mark.parametrize("category,extra", LEGACY_CATEGORIES, ids=[c for c, _ in LEGACY_CATEGORIES])
def test_legacy_owner_can_edit_then_delete(runtime, payload, category, extra):
    """작성자 본인은 모든 기존 모임 종류에서 수정 후 삭제할 수 있다."""
    recruit_id = create_legacy(runtime, payload, category, extra)

    edit = runtime.request("PATCH", f"/api/recruits/{recruit_id}", json={"title": "작성자 수정"}, member=1)
    assert edit.status_code == 200, edit.text
    assert snapshot(runtime, recruit_id)[1]["title"] == "작성자 수정"

    delete = runtime.request("DELETE", f"/api/recruits/{recruit_id}", member=1)
    assert delete.status_code == 200, delete.text
    assert runtime.request("GET", f"/api/recruits/{recruit_id}").status_code == 404


def test_legacy_owner_with_session_cookie_can_edit(runtime, payload):
    """개발용 헤더가 아닌 로그인 세션 쿠키의 작성자도 수정할 수 있다."""
    recruit_id = create_legacy(runtime, payload)

    edit = runtime.request(
        "PATCH", f"/api/recruits/{recruit_id}", json={"title": "세션 수정"}, legacy_login=True
    )

    assert edit.status_code == 200, edit.text
    assert snapshot(runtime, recruit_id)[1]["title"] == "세션 수정"


@pytest.mark.parametrize(
    "actor,expected",
    [(None, 401), (2, 403), (9, 403)],
    ids=["anonymous", "other_member", "admin"],  # 비로그인·다른 회원·ADMIN 역할
)
def test_program_edit_and_delete_keep_creator_only_policy(runtime, payload, actor, expected):
    """신규 프로그램 모임도 개설자만 수정·삭제할 수 있고, 거부 시 데이터가 바뀌지 않는다."""
    created = runtime.request("POST", "/api/recruits", json=json_payload(payload), member=1)
    assert created.status_code == 201, created.text
    recruit_id = created.json()["recruit_id"]
    before = snapshot(runtime, recruit_id)

    edit = runtime.request("PATCH", f"/api/recruits/{recruit_id}", json={"title": "변조"}, member=actor)
    delete = runtime.request("DELETE", f"/api/recruits/{recruit_id}", member=actor)

    assert (edit.status_code, delete.status_code) == (expected, expected), (edit.text, delete.text)
    assert snapshot(runtime, recruit_id) == before


def test_program_creator_can_edit(runtime, payload):
    """신규 프로그램 모임 개설자의 수정은 기존처럼 허용된다."""
    created = runtime.request("POST", "/api/recruits", json=json_payload(payload), member=1)
    recruit_id = created.json()["recruit_id"]

    edit = runtime.request("PATCH", f"/api/recruits/{recruit_id}", json={"title": "개설자 수정"}, member=1)

    assert edit.status_code == 200, edit.text
    assert snapshot(runtime, recruit_id)[1]["title"] == "개설자 수정"
