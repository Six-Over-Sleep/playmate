from app.services.board_service import _is_member_course_board


def test_new_cohort_is_my_course():
    member = {"course": "program:5", "cohort": 36, "role_code": "USER"}
    enrollments = [{"cohort_id": 41, "program_id": 5}]

    assert _is_member_course_board(
        {"scope_type": "COHORT", "cohort_id": 41},
        member, enrollments,
    )
    assert not _is_member_course_board(
        {"scope_type": "COHORT", "cohort_id": 42},
        member, enrollments,
    )


def test_admin_does_not_own_every_cohort():
    member = {"course": "program:5", "cohort": 36, "role_code": "ADMIN"}
    assert not _is_member_course_board(
        {"scope_type": "COHORT", "cohort_id": 42},
        member, [{"cohort_id": 41}],
    )


def test_legacy_cohort_is_my_course():
    member = {"course": "family-ai", "cohort": 36}
    assert _is_member_course_board(
        {"scope_type": "LEGACY", "course_code": "family-ai", "cohort": 36},
        member, [],
    )
