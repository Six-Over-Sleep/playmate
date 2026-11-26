"""공동구매 모임 구매 링크(purchase_url) 저장 경로 회귀 테스트(Issue #82 F6).

실제 main 라우트를 격리 SQLite와 가짜 인증(runtime fixture)으로 호출해
생성·수정 모두 위험한 스킴을 거부하고 정상 http·https 링크는 유지하는지 확인한다.
"""

from backend.tests.recruit.test_runtime_api import runtime  # noqa: F401

OWNER = 1


def group_buy_body(payload, purchase_url):
    return {
        "title": "공동구매",
        "body": "함께 구매합니다.",
        "category": "group_buy",
        "recruit_mode": "short",
        "capacity": 4,
        "product_name": "책",
        "purchase_url": purchase_url,
        "deadline_at": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_start": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_end": payload["ends_at"].replace(tzinfo=None).isoformat(),
    }


def stored_purchase_url(runtime, recruit_id):
    """기존 모임 상세 응답의 카테고리 상세(detail)에 저장된 구매 링크를 읽는다."""
    detail = runtime.request("GET", f"/api/recruits/{recruit_id}", member=OWNER).json()
    return (detail.get("detail") or {}).get("purchase_url")


def test_create_rejects_dangerous_purchase_url(runtime, payload):
    """javascript·data 링크로는 모임을 만들 수 없다(422)."""
    for url in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>"):
        response = runtime.request("POST", "/api/recruits", json=group_buy_body(payload, url), member=OWNER)
        assert response.status_code == 422, (url, response.text)


def test_create_and_update_keep_https_and_reject_unsafe_update(runtime, payload):
    """정상 https 링크는 저장되고, 수정 시 위험한 링크는 거부되어 기존 값이 유지된다."""
    created = runtime.request(
        "POST", "/api/recruits", json=group_buy_body(payload, "https://shop.example.com/a"), member=OWNER
    )
    assert created.status_code == 201, created.text
    recruit_id = created.json()["recruit_id"]
    assert stored_purchase_url(runtime, recruit_id) == "https://shop.example.com/a"

    rejected = runtime.request(
        "PATCH", f"/api/recruits/{recruit_id}", json={"purchase_url": "javascript:alert(1)"}, member=OWNER
    )
    assert rejected.status_code == 422, rejected.text
    assert stored_purchase_url(runtime, recruit_id) == "https://shop.example.com/a"

    updated = runtime.request(
        "PATCH", f"/api/recruits/{recruit_id}", json={"purchase_url": "http://shop.example.com/b"}, member=OWNER
    )
    assert updated.status_code == 200, updated.text
    assert stored_purchase_url(runtime, recruit_id) == "http://shop.example.com/b"
