"""Issue #101: 소속 직접 선택 회원가입 정책 검증 (공유 DB 미사용)."""
from contextlib import contextmanager

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app.schemas.member import MemberSignup
from app.services import member_service


@pytest.mark.parametrize("payload", [
    {"nickname": "성공", "cohort_id": 0},
    {"nickname": "성공", "cohort_id": -1},
    {"nickname": "성공", "cohort_id": "2"},
    {"nickname": "성공", "cohort_id": True},
    {"nickname": "성공", "cohort_id": 2, "track": "family-ai"},
])
def test_signup_invalid_payload(payload):
    with pytest.raises(ValidationError):
        MemberSignup(**payload)


def test_signup_does_not_require_verification():
    member = MemberSignup(nickname="  시험자  ", cohort_id=2)
    assert member.nickname == "시험자"
    assert member.cohort_id == 2


def test_unknown_cohort_rejected_before_member_insert(monkeypatch):
    class Cursor:
        def __init__(self):
            self.statements = []
        def execute(self, sql, params=()):
            self.statements.append(sql)
        def fetchone(self):
            return None
    cursor = Cursor()
    @contextmanager
    def fake_cursor(**kwargs):
        assert kwargs == {"commit": True}
        yield cursor
    monkeypatch.setattr(member_service, "db_cursor", fake_cursor)
    with pytest.raises(HTTPException) as exc:
        member_service.register_member("some-discord-user", MemberSignup(nickname="예시", cohort_id=999))
    assert exc.value.status_code == 422
    assert len(cursor.statements) == 1
    assert "INSERT INTO" not in cursor.statements[0]


def test_no_institution_collision_with_legacy_board(monkeypatch):
    """다른 기관이 같은 program_code를 쓰더라도 과거 과정 게시판에 섞이지 않습니다."""
    info = {
        "cohort_id": 37, "cohort_no": 36, "campus_id": None,
        "program_id": 12, "program_code": "family-ai", "program_name": "AI 학습",
        "institution_id": 19, "institution_code": "other-school", "institution_name": "다른 기관",
        "campus_name": None,
    }
    class Cursor:
        def __init__(self):
            self.results = iter([info, {
                "member_id": 900, "discord_id": "abc", "nickname": "시험자",
                "course": "program:12", "cohort": 36, "role_code": "USER",
            }, {"cohort_id":37}, None])
            self.queries = []
        def execute(self,sql,params=()):
            self.queries.append((sql,params))
        def fetchone(self):
            return next(self.results)
    cursor=Cursor()
    @contextmanager
    def fake_cursor(**kwargs):
        yield cursor
    monkeypatch.setattr(member_service,"db_cursor",fake_cursor)
    member=member_service.register_member("abc",MemberSignup(nickname="시험자",cohort_id=37))
    assert member["course"] == "program:12"
    assert any("INSERT INTO public.boards" in sql and "'COHORT'" in sql for sql,_ in cursor.queries)


def test_education_options_list(monkeypatch):
    class Cursor:
        def execute(self, sql, params=()):
            assert "FROM public.cohorts" in sql
            assert "i.status = 'ACTIVE'" in sql
        def fetchall(self):
            return [{"cohort_id": 2, "institution_name": "플레이데이터", "cohort_no": 36}]
    @contextmanager
    def fake_cursor(**kwargs):
        assert kwargs == {"read_only": True}
        yield Cursor()
    monkeypatch.setattr(member_service,"db_cursor",fake_cursor)
    assert member_service.get_education_options()[0]["cohort_id"] == 2
