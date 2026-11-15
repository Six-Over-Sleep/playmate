"""신규 소속 가입이 단일 트랜잭션이며 Discord DM 기본 ON인지 확인합니다."""
from contextlib import contextmanager

from app.schemas.member import MemberSignup
from app.services import member_service


INFO = {
    "cohort_id": 2, "cohort_no": 36, "campus_id": None,
    "program_id": 1, "program_code": "family-ai", "program_name": "SK네트웍스 Family AI 캠프",
    "institution_id": 1, "institution_code": "playdata", "institution_name": "플레이데이터",
    "campus_name": None,
}


class RecordingCursor:
    def __init__(self):
        self.executed = []
        self.results = iter([
            INFO,  # lookup cohort
            {"member_id": 1, "discord_id": "555", "nickname": "민혁", "course": "family-ai", "cohort": 36, "role_code": "USER"},
            {"cohort_id": 2},  # row lock
            None,  # existing scope COHORT board
            {"board_id": 8},  # legacy Family AI 36 board
        ])

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return next(self.results)


def test_register_member_saves_dm_opt_in_true_and_enrollment(monkeypatch):
    cursor = RecordingCursor()
    commits = []

    @contextmanager
    def fake_cursor(**kwargs):
        commits.append(kwargs.get("commit"))
        yield cursor

    monkeypatch.setattr(member_service, "db_cursor", fake_cursor)
    signup = MemberSignup(nickname="민혁", cohort_id=2)
    result = member_service.register_member("555", signup)

    member_insert = next(row for row in cursor.executed if "INSERT INTO public.members" in row[0])
    enrollment_insert = next(row for row in cursor.executed if "INSERT INTO public.member_enrollments" in row[0])
    assert "external_dm_opt_in" in member_insert[0]
    assert "TRUE" in member_insert[0]
    assert member_insert[1] == ("555", "민혁", "family-ai", 36)
    assert enrollment_insert[1] == (1, 2)
    assert "'ACTIVE'" in enrollment_insert[0]
    assert commits == [True]
    assert result["member_id"] == 1
