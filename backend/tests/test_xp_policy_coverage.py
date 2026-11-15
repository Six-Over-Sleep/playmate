"""코드가 읽는 XP 정책(지급량·한도)이 마이그레이션 초기값에 모두 있는지 확인한다.

정책 행이 없으면 해당 XP 지급 API가 503을 반환하므로, 새 지급 유형이나 한도를
추가할 때 마이그레이션에 행을 함께 추가하지 않으면 이 테스트가 실패한다. DB에 접속하지 않는다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "database" / "sql"
APP = ROOT / "backend" / "app"


def _seeded(table: str) -> set[str]:
    """마이그레이션의 INSERT INTO <table> ... VALUES 블록에 들어 있는 키."""
    keys = set()
    for path in sorted(SQL_DIR.glob("*.sql")):
        for block in re.findall(rf"INSERT INTO {table}\b.*?;", path.read_text(encoding="utf-8"), re.S):
            keys.update(re.findall(r"\('([A-Z0-9_]+)',\s*\d+\)", block))
    return keys


def _app_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in APP.rglob("*.py"))


def _award_types_read_by_code() -> set[str]:
    text = _app_text()
    found = set(re.findall(r'read_xp_amount\(\s*cursor,\s*"([A-Z0-9_]+)"', text))
    # 접두어와 변수로 조합하는 유형
    from backend.app.services.meetup_xp_service import MEETUP_REWARD_TYPES
    from backend.app.services.skill_xp_service import SKILL_ACTIVITY_TYPES

    found.update(f"MEETUP_{reward}" for reward in MEETUP_REWARD_TYPES)
    found.update(f"SKILL_{kind}" for kind in SKILL_ACTIVITY_TYPES)
    found.update({"ATTEND", "POST", "COMMENT", "REPLY", "STREAK_7", "STREAK_30"})
    found.update({"CAREER_DOCUMENT", "CAREER_INTERVIEW", "CAREER_SUCCESS"})
    return found


def test_every_award_policy_read_by_code_is_seeded():
    missing = _award_types_read_by_code() - _seeded("xp_award_policies")
    assert not missing, f"xp_award_policies 초기값에 없는 정책: {sorted(missing)}"


def test_every_limit_policy_read_by_code_is_seeded():
    used = set(re.findall(r'"([A-Z0-9_]+(?:_COUNT|_PER_POST))"', _app_text()))
    assert used, "read_xp_limit 키를 찾지 못했습니다."
    missing = used - _seeded("xp_limit_policies")
    assert not missing, f"xp_limit_policies 초기값에 없는 한도: {sorted(missing)}"


def test_xp_rules_are_not_hardcoded():
    xp = (APP / "services" / "xp_service.py").read_text(encoding="utf-8")
    skill = (APP / "services" / "skill_xp_service.py").read_text(encoding="utf-8")
    mypage = (APP / "routers" / "mypage.py").read_text(encoding="utf-8")
    assert 'read_xp_amount(cursor, "CAREER_SPEC_PUBLIC")' in mypage
    assert "total_xp + 50" not in mypage
    assert "limit = 3 if" not in xp and "10 - cursor" not in xp
    assert "streak not in (7, 30)" not in xp
    assert "SKILL_XP_RULES" not in skill
