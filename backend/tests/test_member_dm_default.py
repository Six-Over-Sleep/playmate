"""신규 회원 가입 시 Discord DM 알림(external_dm_opt_in)을 기본 ON으로 저장하는지 DB 없이 확인한다."""
from contextlib import contextmanager

from app.schemas.member import MemberSignup
from app.services import member_service


class RecordingCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return {"member_id": 1, "discord_id": "555", "nickname": "민혁",
                "course": "백엔드", "cohort": 1, "role_code": "USER"}


def test_register_member_saves_dm_opt_in_true(monkeypatch):
    cursor = RecordingCursor()
    commits = []

    @contextmanager
    def db_cursor(**kwargs):
        commits.append(kwargs.get("commit"))
        yield cursor

    monkeypatch.setattr(member_service, "db_cursor", db_cursor)
    signup = MemberSignup(nickname="민혁", track="family-ai", cohort=1)

    result = member_service.register_member("555", signup)

    sql, params = cursor.executed[0]
    assert "external_dm_opt_in" in sql
    assert "VALUES (%s, %s, %s, %s, %s, TRUE)" in sql
    assert params == ("555", "민혁", "family-ai", 1, "USER")  # 기존 입력값·순서는 그대로
    assert commits == [True]
    assert result["member_id"] == 1
