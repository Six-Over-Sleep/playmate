"""취업 게시글 Discord 공유 대상 정책 (순수 함수, DB/Discord/AWS에 의존하지 않는다).

허용 목록(allow-list)만 공유한다. 새 분류가 추가돼도 여기에 넣기 전에는 공유되지 않는다.
SQL 조회 조건도 이 상수에서 만든다 (repository가 같은 값을 쓰고, 조회 결과를 `classify`로 한 번 더 검증한다).
"""
from typing import NamedTuple

KIND_IMMEDIATE = "IMMEDIATE"   # 등록 후 곧바로 공유 (후기)
KIND_DIGEST = "DIGEST"         # 매일 20:00 KST 묶음 공유 (연구소 정보)

# category_code -> {subcategory_code: kind}
ALLOWED = {
    "reviews": {"INTERVIEW": KIND_IMMEDIATE, "SUCCESS": KIND_IMMEDIATE, "FINAL": KIND_IMMEDIATE},
    "lab": {"JOB_STRATEGY": KIND_DIGEST, "CERTIFICATION": KIND_DIGEST, "JOB_COMPARISON": KIND_DIGEST},
}
IMMEDIATE_CATEGORY = "reviews"
IMMEDIATE_SUBCATEGORIES = tuple(ALLOWED["reviews"])
DIGEST_CATEGORY = "lab"
DIGEST_SUBCATEGORIES = tuple(ALLOWED["lab"])

DIGEST_LABELS = {"JOB_STRATEGY": "취업 전략", "CERTIFICATION": "자격증", "JOB_COMPARISON": "직무 비교"}


class Target(NamedTuple):
    kind: str
    label: str


def kind_of(category_code, subcategory_code) -> str | None:
    """허용 목록에 있으면 공유 종류(IMMEDIATE/DIGEST), 아니면 None. 대소문자·공백을 보정하지 않는다 (정확히 일치만)."""
    if not isinstance(category_code, str) or not isinstance(subcategory_code, str):
        return None
    return ALLOWED.get(category_code, {}).get(subcategory_code)


def review_label(subcategory_code: str, process_result) -> str:
    """후기 라벨. SUCCESS라는 코드만으로 합격이라고 하지 않고 process_result='PASS'가 확인될 때만 '합격 후기'."""
    if subcategory_code == "INTERVIEW":
        return "면접 후기"
    if subcategory_code == "SUCCESS":
        return "합격 후기" if process_result == "PASS" else "최종 결과 후기"
    return "최종 결과 후기"  # FINAL


def classify(category_code, subcategory_code, process_result=None) -> Target | None:
    kind = kind_of(category_code, subcategory_code)
    if kind is None:
        return None
    if kind == KIND_IMMEDIATE:
        return Target(kind, review_label(subcategory_code, process_result))
    return Target(kind, DIGEST_LABELS[subcategory_code])
