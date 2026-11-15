"""코드가 읽는 XP 정책 유형이 023 마이그레이션 초기값에 모두 있는지 확인한다.

정책 행이 없으면 해당 XP 지급 API가 503을 반환하므로, 새 지급 유형을 추가할 때
023에 행을 함께 추가하지 않으면 이 테스트가 실패한다. DB에 접속하지 않는다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "database" / "sql" / "023_xp_award_policies.sql"
APP = ROOT / "backend" / "app"


def _policy_rows() -> set[str]:
    return set(re.findall(r"\('([A-Z0-9_]+)',\s*\d+\)", MIGRATION.read_text(encoding="utf-8")))


def _types_read_by_code() -> set[str]:
    found = set()
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found.update(re.findall(r'read_xp_amount\(\s*cursor,\s*"([A-Z0-9_]+)"', text))
    # 접두어와 변수로 조합하는 유형
    from backend.app.services.meetup_xp_service import MEETUP_REWARD_TYPES

    found.update(f"MEETUP_{reward}" for reward in MEETUP_REWARD_TYPES)
    found.update({"ATTEND", "POST", "COMMENT", "REPLY", "STREAK_7", "STREAK_30"})
    found.update({"CAREER_DOCUMENT", "CAREER_INTERVIEW", "CAREER_SUCCESS"})
    return found


def test_every_policy_read_by_code_is_seeded():
    missing = _types_read_by_code() - _policy_rows()
    assert not missing, f"023_xp_award_policies.sql에 없는 정책: {sorted(missing)}"


def test_career_spec_public_reads_policy_instead_of_constant():
    text = (APP / "routers" / "mypage.py").read_text(encoding="utf-8")
    assert 'read_xp_amount(cursor, "CAREER_SPEC_PUBLIC")' in text
    assert "total_xp + 50" not in text
