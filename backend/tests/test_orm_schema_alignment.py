import pytest
from sqlalchemy.dialects import postgresql

from backend.app.models.member import Member
from backend.app.models.post import Post
from backend.app.models.recruit import Recruit, RecruitMember
from backend.app.models.recruit_program import RecruitSkill


def test_member_removed_columns():
    columns = set(Member.__table__.columns.keys())
    assert not columns.intersection({
        "public_anonymous_id",
        "student_verification_status",
        "verified_at",
    })


def test_member_status_not_nullable():
    column = Member.__table__.c.member_status
    assert column.nullable is False


@pytest.mark.parametrize(
    "model,column,expected",
    [
        (Member, "role_code", "VARCHAR(20)"),
        (Member, "member_status", "VARCHAR(20)"),
        (Member, "nickname", "VARCHAR(50)"),
        (Member, "profile_image_url", "VARCHAR(500)"),
        (Post, "post_status", "VARCHAR(20)"),
        (Post, "post_type", "VARCHAR(30)"),
        (Post, "source_type", "VARCHAR(20)"),
        (Post, "tag_name", "VARCHAR(30)"),
        (Post, "title", "VARCHAR(100)"),
        (Recruit, "category", "VARCHAR(20)"),
        (Recruit, "close_reason", "VARCHAR(30)"),
        (Recruit, "contact_method", "VARCHAR(255)"),
        (Recruit, "place", "VARCHAR(255)"),
        (Recruit, "recruit_mode", "VARCHAR(20)"),
        (Recruit, "regular_days", "TEXT[]"),
        (Recruit, "state", "VARCHAR(20)"),
        (RecruitMember, "role", "VARCHAR(20)"),
        (RecruitMember, "status", "VARCHAR(20)"),
        (RecruitSkill, "name", "VARCHAR(100)"),
        (RecruitSkill, "skill_code", "VARCHAR(64)"),
    ],
)
def test_orm_column_types(model, column, expected):
    actual = str(
        model.__table__.c[column].type.compile(
            dialect=postgresql.dialect()
        )
    ).upper()

    assert actual == expected
