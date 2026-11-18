# PLAYMATE_COURSE_BOARD_PERMISSIONS_V1
# PLAYMATE_COMMENT_ANON_EDIT_V2
# PLAYMATE_BOARD_ANONYMOUS_V1
"""게시판 업무 순서·권한·트랜잭션을 관리한다."""

# Any : 반환되는 DB 데이터(딕셔너리)의 값 타입을 유연하게 표현함.
from typing import Any
import re

# HTTPException : API 요청 처리 중 HTTP 오류 응답을 발생시킴.
from fastapi import HTTPException
# errors : PostgreSQL 제약조건 위반 등의 DB 오류를 구분함.
from psycopg2 import errors

# db_cursor : DB 커서를 생성하고 조회/저장 트랜잭션을 관리함.
from app.core.db_connect import CommitOutcomeUnknownError, db_cursor
from app.core.uploads import MAX_POST_IMAGES, remove_saved_images, store_validated_images
# repository : 게시판·게시글·댓글에 대한 실제 SQL 실행을 담당함.
from backend.app.repositories import board_repository as repository
import logging
from backend.app.services.xp_service import (
    grant_xp,
    revoke_xp,
    grant_post_like_xp,
)
from backend.app.services.notification_writer import save_comment_notification

logger = logging.getLogger(__name__)

# =========================================================
# 1. 게시판 및 게시글 존재 여부 확인 (공통 함수)
# =========================================================
def _require_board(cursor, board_id: int) -> dict[str, Any]:
    """게시판을 조회하고 없으면 기존 404 응답으로 처리한다."""
    # 게시판 ID로 DB에서 게시판 정보를 조회함.
    board = repository.get_board(cursor, board_id)
    # 해당 게시판이 존재하지 않으면 404(Not Found) 오류 발생
    if board is None:
        raise HTTPException(status_code=404, detail="게시판을 찾을 수 없습니다.")
    return board



def _get_board_member(cursor, member_id: int) -> dict[str, Any]:
    """세션 회원 ID로 서버 DB의 과정·기수를 조회합니다."""
    cursor.execute(
        "SELECT course, cohort, role_code FROM members WHERE member_id = %s",
        (member_id,),
    )
    member = cursor.fetchone()
    if member is None:
        raise HTTPException(status_code=401, detail="회원 정보를 찾을 수 없습니다.")
    return member


def _can_write_course_board(board: dict[str, Any], member: dict[str, Any]) -> bool:
    """일반 게시판은 그대로 두고, 과정 게시판만 과정+기수 일치를 요구합니다."""
    if board.get("course_code") is None:
        return True
    if (member.get("role_code") or "").strip().upper() == "ADMIN":
        return True
    return (
        member.get("course") == board.get("course_code")
        and member.get("cohort") == board.get("cohort")
    )


def _verified_enrollments(cursor, member_id: int) -> list[dict[str, Any]]:
    """활성 소속과 수료 소속을 조회합니다. 교육 종료일에는 접근을 제한하지 않습니다."""
    cursor.execute(
        """
        SELECT c.cohort_id, c.program_id, c.institution_id
        FROM public.member_enrollments AS e
        JOIN public.cohorts AS c ON c.cohort_id = e.cohort_id
        WHERE e.member_id = %s
          AND e.enrollment_status IN ('ACTIVE', 'COMPLETED')
        """,
        (member_id,),
    )
    return list(cursor.fetchall())


def _can_access_board(
    board: dict[str, Any],
    member: dict[str, Any],
    enrollments: list[dict[str, Any]],
    *,
    write: bool,
) -> bool:
    """LEGACY 정책은 유지하고 신규 범위는 활성/수료 소속을 기준으로 확인합니다."""
    scope = board.get("scope_type", "LEGACY")
    if scope == "LEGACY":
        return _can_write_course_board(board, member) if write else True

    if scope not in {"NATIONAL", "INSTITUTION", "PROGRAM", "COHORT"}:
        return False  # 알 수 없는 범위는 허용하지 않습니다.

    if (member.get("role_code") or "").strip().upper() == "ADMIN":
        return True

    if write:
        if board.get("write_policy") != "SCOPE_ONLY":
            return False  # STAFF_ONLY는 관리자 분기에서만 허용됩니다.
    elif board.get("read_policy") == "ALL_VERIFIED":
        return bool(enrollments)
    elif board.get("read_policy") != "SCOPE_ONLY":
        return False

    if scope == "NATIONAL":
        return bool(enrollments)

    key = {
        "INSTITUTION": "institution_id",
        "PROGRAM": "program_id",
        "COHORT": "cohort_id",
    }[scope]
    target_id = board.get(key)
    return (
        isinstance(target_id, int)
        and target_id > 0
        and any(enrollment.get(key) == target_id for enrollment in enrollments)
    )


def _require_board_read_access(
    cursor, board: dict[str, Any], member_id: int
) -> None:
    """이미 조회한 게시판에 대해 추가 조회 없이(LEGACY) 접근 권한을 확인합니다."""
    if board.get("scope_type", "LEGACY") == "LEGACY":
        return

    member = _get_board_member(cursor, member_id)
    if not _can_access_board(
        board, member, _verified_enrollments(cursor, member_id), write=False
    ):
        raise HTTPException(status_code=403, detail="이 게시판을 열람할 권한이 없습니다.")


def _require_board_reader(cursor, board_id: int, member_id: int) -> dict[str, Any]:
    """게시판 상세·게시글·댓글·반응 조회의 공통 읽기 권한 검사."""
    board = _require_board(cursor, board_id)
    _require_board_read_access(cursor, board, member_id)
    return board


def _require_comment_board_reader(cursor, comment_id: int, member_id: int) -> None:
    """댓글 ID만 전달되는 조회에서도 소속 게시판의 접근 권한을 검사합니다."""
    cursor.execute(
        """
        SELECT p.board_id
        FROM public.comments AS c
        JOIN public.posts AS p ON p.post_id = c.post_id
        WHERE c.comment_id = %s AND c.deleted_at IS NULL
        """,
        (comment_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
    _require_board_reader(cursor, row["board_id"], member_id)


def _require_course_board_writer(cursor, board_id: int, member_id: int) -> None:
    """기존 과정 게시판과 신규 범위 게시판의 쓰기 정책을 일관되게 검사합니다."""
    board = _require_board(cursor, board_id)
    if board.get("scope_type", "LEGACY") == "LEGACY":
        if board.get("course_code") is None:
            return
        if not _can_write_course_board(board, _get_board_member(cursor, member_id)):
            raise HTTPException(
                status_code=403,
                detail="이 게시판은 해당 과정·기수 수강생만 작성할 수 있습니다.",
            )
        return

    member = _get_board_member(cursor, member_id)
    if not _can_access_board(
        board, member, _verified_enrollments(cursor, member_id), write=True
    ):
        raise HTTPException(status_code=403, detail="이 게시판에 작성할 권한이 없습니다.")


def _require_comment_board_writer(cursor, comment_id: int, member_id: int) -> None:
    """댓글 수정·삭제 API는 댓글 ID만 받으므로 부모 게시판을 추적합니다."""
    cursor.execute(
        """
        SELECT p.board_id
        FROM comments AS c
        JOIN posts AS p ON p.post_id = c.post_id
        WHERE c.comment_id = %s AND c.deleted_at IS NULL
        """,
        (comment_id,),
    )
    comment = cursor.fetchone()
    if comment is not None:
        _require_course_board_writer(cursor, comment["board_id"], member_id)


def _require_notice_admin(cursor, board_id: int, member_id: int):
    """공지사항 게시판은 관리자만 변경할 수 있도록 검사"""

    board = _require_board(cursor, board_id)

    # 일반 게시판은 기존 권한 유지
    if board["name"] != "공지사항":
        return

    # 관리자 권한 확인
    cursor.execute(
        """
        SELECT role_code
        FROM members
        WHERE member_id = %s
        """,
        (member_id,),
    )

    member = cursor.fetchone()

    if (
        not member
        or (member["role_code"] or "").strip().upper() != "ADMIN"
    ):
        raise HTTPException(
            status_code=403,
            detail="공지사항은 관리자만 작성, 수정, 삭제할 수 있습니다.",
        )

def _require_post(cursor, board_id: int, post_id: int) -> None:
    """댓글·좋아요·스크랩 처리에 필요한 게시글 존재 여부만 검증한다."""
    # 게시판에 속하는 유효한 게시글이 있는지만 확인함.
    if not repository.post_exists(cursor, board_id, post_id):
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")


def _post_detail(cursor, board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    """주어진 커서로 게시글 응답을 구성하고 누락 시 404를 발생시킨다."""
    # 게시글 상세 정보와 작성자 여부, 이미지 등을 조회함.
    post = repository.get_post(cursor, board_id, post_id, member_id)
    if post is None:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    return post


def _comment_detail(cursor, comment_id: int, member_id: int) -> dict[str, Any]:
    """주어진 커서로 댓글 응답을 구성하고 누락 시 404를 발생시킨다."""
    # 댓글 ID에 해당하는 상세 정보를 조회함.
    comment = repository.get_comment(cursor, comment_id, member_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
    return comment


# =========================================================
# 2. 게시판 목록·생성·상세 조회
# =========================================================

def _is_member_course_board(board, member, enrollments) -> bool:
    """Identify the member's actual cohort, regardless of admin rights."""
    scope = board.get("scope_type") or "LEGACY"

    if scope == "COHORT":
        cohort_id = board.get("cohort_id")
        return cohort_id is not None and any(
            enrollment.get("cohort_id") == cohort_id
            for enrollment in enrollments
        )

    if scope == "LEGACY" and board.get("course_code") is not None:
        return (
            member.get("course") == board.get("course_code")
            and member.get("cohort") == board.get("cohort")
        )

    return False


def list_boards(member_id: int | None = None) -> list[dict[str, Any]]:
    """읽을 수 있는 게시판만 반환하며 작성 권한을 계산합니다."""
    with db_cursor(read_only=True) as cursor:
        boards = repository.list_boards(cursor, member_id)
        if member_id is None:
            return [b for b in boards if b.get("scope_type", "LEGACY") == "LEGACY"]

        member = _get_board_member(cursor, member_id)
        needs_enrollment = any(
            b.get("scope_type", "LEGACY") != "LEGACY" for b in boards
        )
        enrollments = _verified_enrollments(cursor, member_id) if needs_enrollment else []
        visible = []
        for board in boards:
            if not _can_access_board(board, member, enrollments, write=False):
                continue
            board["is_my_course"] = _is_member_course_board(board, member, enrollments)
            board["can_write"] = _can_access_board(
                board, member, enrollments, write=True
            )
            # 공지사항은 별도의 관리자 전용 작성 정책을 유지합니다.
            if board.get("name") == "공지사항":
                board["can_write"] = (
                    (member.get("role_code") or "").strip().upper() == "ADMIN"
                )
            visible.append(board)
        return visible


def create_board(
    name: str, description: str | None, creation_reason: str | None, member_id: int
) -> dict[str, Any]:
    """게시판 저장·응답 조회를 한 트랜잭션으로 처리한다. 이름 중복은 409이다."""
    reserved = re.fullmatch(
        r"(?:패밀리 AI|멀티 에이전트|데이터 엔지니어링|데이터·머신러닝) [1-9][0-9]*기",
        name.strip(),
    )
    if name.strip().casefold() in {"공지사항", "명예의 전당", "hot 게시판"} or reserved:
        raise HTTPException(status_code=403, detail="운영 전용 게시판 이름입니다.")
    try:
        with db_cursor(commit=True) as cursor:
            board_id = repository.create_board(
                cursor, name, description or None, creation_reason or None, member_id
            )
            return _require_board(cursor, board_id)
    except errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409, detail="이미 같은 이름의 게시판이 있습니다."
        ) from exc






def get_board(board_id: int, member_id: int | None = None) -> dict[str, Any]:
    """게시판 상세 조회에서도 권한 검사를 수행합니다."""
    with db_cursor(read_only=True) as cursor:
        board = _require_board(cursor, board_id)
        if member_id is None:
            if board.get("scope_type", "LEGACY") != "LEGACY":
                raise HTTPException(status_code=403, detail="로그인이 필요합니다.")
            return board

        member = _get_board_member(cursor, member_id)
        enrollments = (
            _verified_enrollments(cursor, member_id)
            if board.get("scope_type", "LEGACY") != "LEGACY"
            else []
        )
        if not _can_access_board(board, member, enrollments, write=False):
            raise HTTPException(status_code=403, detail="이 게시판을 열람할 권한이 없습니다.")
        board["is_my_course"] = _is_member_course_board(board, member, enrollments)
        board["can_write"] = _can_access_board(board, member, enrollments, write=True)
        if board.get("name") == "공지사항":
            board["can_write"] = (
                (member.get("role_code") or "").strip().upper() == "ADMIN"
            )
        return board


# =========================================================
# 3. 게시글 목록·생성·상세 조회
# =========================================================
def list_posts(
    board_id: int, q: str | None, sort: str, member_id: int
) -> list[dict[str, Any]]:
    """게시판 확인 후 검색 목록을 반환한다. 기존 latest 정렬만 허용한다.

    q는 공백을 제거하고 member_id는 작성자 표시 계산에 사용한다.
    게시판·목록·이미지 조회는 한 연결을 사용하며 이미지 N+1을 방지한다.
    """
    # 현재 지원하는 정렬 방식은 latest(최신순)뿐임.
    if sort != "latest":
        raise HTTPException(status_code=422, detail="sort는 latest만 지원합니다.")
    with db_cursor(read_only=True) as cursor:
        # 이미 조회한 게시판을 재사용하여 LEGACY에서 추가 DB 왕복을 피합니다.
        board = _require_board(cursor, board_id)
        _require_board_read_access(cursor, board, member_id)
        # 검색어가 없으면 빈 문자열 사용, 있으면 양쪽 공백 제거 후 조회함.
        return repository.list_posts(cursor, board_id, (q or "").strip(), member_id)


def list_featured_posts(kind: str, q: str | None, member_id: int) -> list[dict[str, Any]]:
    """좋아요 집계 기반 읽기 전용 인기 목록."""
    if kind not in {"hall-of-fame", "hot"}:
        raise HTTPException(status_code=404, detail="인기 게시판을 찾을 수 없습니다.")
    with db_cursor(read_only=True) as cursor:
        # DB 쿼리의 LIMIT 100 전에 권한으로 게시판을 제한해야
        # 비공개 게시글이 HOT/명예의 전당에서 노출되거나 랭킹을 밀어내지 않습니다.
        boards = repository.list_boards(cursor)
        member = _get_board_member(cursor, member_id)
        needs_enrollment = any(
            b.get("scope_type", "LEGACY") != "LEGACY" for b in boards
        )
        enrollments = _verified_enrollments(cursor, member_id) if needs_enrollment else []
        allowed_ids = [
            b["id"] for b in boards
            if _can_access_board(b, member, enrollments, write=False)
        ]
        return repository.list_featured_posts(
            cursor, kind, (q or "").strip(), member_id,
            allowed_board_ids=allowed_ids,
        )


def create_post(
    board_id: int,
    title: str,
    body: str,
    member_id: int,
    images: list[dict[str, Any]] | None = None,
    is_anonymous: bool = False,
) -> dict[str, Any]:
    """게시글 생성 및 작성 XP 지급"""

    # 1. 게시글 저장
    with db_cursor(commit=True) as cursor:

        # 과정 게시판은 해당 과정·기수만 작성 가능
        _require_course_board_writer(cursor, board_id, member_id)
        # 공지사항 관리자 권한 검사
        _require_notice_admin(cursor, board_id, member_id)

        # 공지사항은 관리자 이름으로 작성되며 익명 선택 불가
        if is_anonymous and _require_board(cursor, board_id)["name"] == "공지사항":
            raise HTTPException(status_code=422, detail="공지사항은 익명으로 작성할 수 없습니다.")

        # 게시글 DB 저장
        post_id = repository.create_post(
            cursor,
            board_id,
            title,
            body,
            member_id,
            images,
            is_anonymous,
        )

        # 저장한 게시글 정보 조회
        post = _post_detail(
            cursor,
            board_id,
            post_id,
            member_id,
        )

    # 2. 게시글 작성 XP 지급
    if member_id > 0:
        try:
            result = grant_xp(
                member_id,
                "POST",
                post_id,
            )

            if result.get("awarded"):
                logger.info(
                    "게시글 작성 XP 지급 완료: member_id=%s, post_id=%s, xp=%s",
                    member_id,
                    post_id,
                    result.get("earned_xp"),
                )
            else:
                logger.info(
                    "게시글 작성 XP 미지급: member_id=%s, post_id=%s, reason=%s",
                    member_id,
                    post_id,
                    result.get("reason"),
                )

        except Exception:
            logger.exception(
                "게시글 XP 지급 실패: post_id=%s",
                post_id,
            )

    # 3. 생성된 게시글 반환
    return post


def get_post(board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    """게시판·게시글 ID의 상세를 반환한다. 삭제·모임 게시글은 404이다."""
    with db_cursor(read_only=True) as cursor:
        _require_board_reader(cursor, board_id, member_id)
        # Repository의 게시글 조회 조건으로 삭제·모임 게시글을 제외함.
        return _post_detail(cursor, board_id, post_id, member_id)


# =========================================================
# 4. 게시글 수정·삭제 및 작성자 권한 확인
# =========================================================
def _raise_post_permission(cursor, board_id: int, post_id: int) -> None:
    """변경 실패 시 존재하는 글은 403, 없는 글은 404로 구분한다."""
    # 글이 없으면 _require_post()에서 404를 발생시킴.
    _require_post(cursor, board_id, post_id)
    # 글은 존재하지만 수정·삭제 조건에 맞지 않으면 403(Forbidden) 반환
    raise HTTPException(
        status_code=403, detail="작성자만 수정하거나 삭제할 수 있습니다."
    )


def update_post(
    board_id: int, post_id: int, title: str, body: str, member_id: int,
    is_anonymous: bool | None = None,
    *,
    original_image_ids: list[int] | None = None,
    keep_image_ids: list[int] | None = None,
    new_images: list[tuple[dict, bytes]] | None = None,
) -> dict[str, Any]:
    """작성자 조건으로 수정 후 응답을 조회한다. 실패 시 전체 롤백한다."""
    removed = []
    saved = []
    try:
        with db_cursor(commit=True) as cursor:
            _require_notice_admin(cursor, board_id, member_id)
            _require_course_board_writer(cursor, board_id, member_id)
            if is_anonymous and _require_board(cursor, board_id)["name"] == "공지사항":
                raise HTTPException(status_code=422, detail="공지사항은 익명으로 작성할 수 없습니다.")
            # Repository에서 작성자 ID와 게시글 상태를 조건으로 수정함.
            # 수정된 행이 없으면 권한 부족(403) 또는 글 없음(404)을 판별함.
            if not repository.update_post(
                cursor, board_id, post_id, title, body, member_id, is_anonymous
            ):
                _raise_post_permission(cursor, board_id, post_id)
            if original_image_ids is not None:
                current_ids = repository.post_image_ids(cursor, post_id)
                keep = keep_image_ids or []
                if len(set(keep)) != len(keep) or not set(keep) <= set(original_image_ids):
                    raise HTTPException(422, "유지할 이미지 정보가 올바르지 않습니다.")
                if set(original_image_ids) != current_ids:
                    raise HTTPException(409, "첨부 이미지가 변경되었습니다. 새로고침 후 다시 수정해 주세요.")
                added = new_images or []
                if len(keep) + len(added) > MAX_POST_IMAGES:
                    raise HTTPException(422, f"이미지는 최대 {MAX_POST_IMAGES}장까지 첨부할 수 있습니다.")
                removed = repository.remove_post_images(cursor, post_id, keep)
                saved = store_validated_images(added)
                repository.insert_post_images(cursor, post_id, saved, start_order=len(keep))
            result = _post_detail(cursor, board_id, post_id, member_id)
    except CommitOutcomeUnknownError:
        raise
    except Exception:
        try:
            remove_saved_images(saved)
        except Exception:
            logger.exception("수정 실패 후 새 이미지 정리 실패: post_id=%s", post_id)
        raise

    try:
        remove_saved_images(removed)
    except Exception:
        logger.exception("수정 커밋 후 기존 이미지 정리 실패: post_id=%s", post_id)
    return result



# 게시글 삭제 및 XP 회수
def delete_post(board_id: int, post_id: int, member_id: int) -> None:
    with db_cursor(commit=True) as cursor:
        _require_notice_admin(cursor, board_id, member_id)
        _require_course_board_writer(cursor, board_id, member_id)

        # 1. 게시글 논리 삭제
        if not repository.delete_post(cursor, board_id, post_id, member_id):
            _raise_post_permission(cursor, board_id, post_id)

        # 2. 게시글 작성 XP 회수
        revoke_xp(cursor, member_id, "POST", post_id)

# =========================================================
# 5. 게시글 좋아요·스크랩
# =========================================================
# 게시글 좋아요 및 작성자 XP 지급
def like_post(
    board_id: int,
    post_id: int,
    member_id: int,
) -> dict[str, Any]:

    with db_cursor(commit=True) as cursor:

        _require_board_reader(cursor, board_id, member_id)
        # 1. 게시글 존재 여부 확인
        _require_post(cursor, board_id, post_id)

        # 2. 좋아요 등록
        # 처음 등록하면 True, 중복 요청이면 False
        is_new_like = repository.like_post(
            cursor, post_id, member_id
        )

        # 3. 새로운 좋아요일 때만 XP 지급
        if is_new_like:
            grant_post_like_xp(
                cursor,
                post_id,
                member_id,
            )

        # 4. 현재 좋아요 상태 반환
        return repository.get_post_like(
            cursor, post_id, member_id
        )

def unlike_post(board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    """게시글 확인 후 좋아요를 취소하고 응답을 조회한다. 좋아요가 없어도 성공한다."""
    with db_cursor(commit=True) as cursor:
        _require_board_reader(cursor, board_id, member_id)
        _require_post(cursor, board_id, post_id)
        repository.unlike_post(cursor, post_id, member_id)
        return repository.get_post_like(cursor, post_id, member_id)


def scrap_post(board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    """게시글 확인·스크랩 저장·응답 조회를 한 트랜잭션에서 수행한다.

    이미 스크랩한 글에 다시 요청해도 행을 추가하지 않고 현재 상태를 반환한다.
    삭제·모임 게시글은 404이다.
    """
    with db_cursor(commit=True) as cursor:
        _require_board_reader(cursor, board_id, member_id)
        _require_post(cursor, board_id, post_id)
        repository.scrap_post(cursor, post_id, member_id)
        return repository.get_post_scrap(cursor, post_id, member_id)


def unscrap_post(board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    """게시글 확인 후 스크랩을 취소하고 응답을 조회한다. 스크랩이 없어도 성공한다."""
    with db_cursor(commit=True) as cursor:
        _require_board_reader(cursor, board_id, member_id)
        _require_post(cursor, board_id, post_id)
        repository.unscrap_post(cursor, post_id, member_id)
        return repository.get_post_scrap(cursor, post_id, member_id)



# =========================================================
# 6. 댓글 목록·생성·상세 조회
# =========================================================
def list_comments(board_id: int, post_id: int, member_id: int) -> list[dict[str, Any]]:
    """게시글 확인 후 댓글을 반환한다. 불필요한 상세·이미지 조회를 생략한다."""
    with db_cursor(read_only=True) as cursor:
        _require_board_reader(cursor, board_id, member_id)
        # 댓글이 속한 게시글이 실제로 존재하는지 확인함.
        _require_post(cursor, board_id, post_id)
        # 삭제되지 않은 댓글 목록을 조회함.
        return repository.list_comments(cursor, post_id, member_id)


def _require_parent_comment(cursor, post_id: int, parent_comment_id: int) -> None:
    """대댓글의 부모가 같은 글의 삭제되지 않은 최상위 댓글인지 검증한다.

    없거나 삭제된 부모는 404, 다른 글의 댓글이거나 대댓글에 다시 답글을 달면 422이다.
    """
    parent = repository.get_parent_comment(cursor, parent_comment_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="부모 댓글을 찾을 수 없습니다.")

    # 다른 게시글의 댓글에는 답글 작성 불가
    if parent["post_id"] != post_id:
        raise HTTPException(
            status_code=422,
            detail="같은 게시글의 댓글에만 답글을 작성할 수 있습니다.",
        )

    # 대댓글에 다시 답글 작성 불가 (1단계까지만 허용)
    if parent["parent_comment_id"] is not None:
        raise HTTPException(
            status_code=422, detail="대댓글에는 답글을 작성할 수 없습니다."
        )


# 댓글 및 대댓글 작성
def create_comment(
    board_id: int,
    post_id: int,
    body: str,
    member_id: int,
    parent_comment_id: int | None = None,
    is_anonymous: bool = False,
) -> dict[str, Any]:
    """게시글·부모 댓글 확인, 댓글 저장, 응답 조회를 한 트랜잭션에서 수행한다."""
    with db_cursor(commit=True) as cursor:
        # 1. 게시글 및 과정·기수 작성 권한 확인
        _require_post(cursor, board_id, post_id)
        _require_course_board_writer(cursor, board_id, member_id)

        # 2. 대댓글이면 부모 댓글 검증
        if parent_comment_id is not None:
            _require_parent_comment(cursor, post_id, parent_comment_id)

        # 3. 댓글 또는 대댓글 저장
        comment_id = repository.create_comment(
            cursor,
            post_id,
            body,
            member_id,
            parent_comment_id,
            is_anonymous,
        )

        comment = _comment_detail(
            cursor, comment_id, member_id
        )

    # 4. DB 저장 완료 후 XP 지급
    if member_id > 0:
        activity_type = (
            "REPLY" if parent_comment_id is not None
            else "COMMENT"
        )

        try:
            grant_xp(member_id, activity_type, comment_id)
        except Exception:
            logger.exception(
                "댓글 XP 지급 실패: comment_id=%s",
                comment_id
            )

    # 5. DB 저장 완료 후 Discord DM 알림 대기 행 저장 (실패해도 댓글은 유지)
    try:
        save_comment_notification(post_id, comment_id, member_id, parent_comment_id)
    except Exception:
        logger.exception(
            "댓글 알림 저장 실패: comment_id=%s",
            comment_id
        )

    return comment


def get_comment(comment_id: int, member_id: int) -> dict[str, Any]:
    """댓글 상세를 반환한다. 없거나 접근 불가한 댓글은 조회하지 않습니다."""
    with db_cursor(read_only=True) as cursor:
        _require_comment_board_reader(cursor, comment_id, member_id)
        return _comment_detail(cursor, comment_id, member_id)


# =========================================================
# 7. 댓글 수정·삭제 및 작성자 권한 확인
# =========================================================
def _raise_comment_permission(cursor, comment_id: int) -> None:
    """댓글 변경 실패를 작성자 권한 부족과 데이터 누락으로 구분한다."""
    # 댓글이 남아 있으면 작성자 권한이 없다고 판단하여 403 반환
    if repository.comment_exists(cursor, comment_id):
        raise HTTPException(
            status_code=403, detail="작성자만 수정하거나 삭제할 수 있습니다."
        )
    # 존재하지 않거나 이미 삭제된 댓글이면 404 반환
    raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")


def update_comment(
    comment_id: int,
    body: str,
    member_id: int,
    is_anonymous: bool | None = None,
) -> dict[str, Any]:
    """작성자만 본문/익명 여부를 수정합니다. None이면 익명 여부를 유지합니다."""
    with db_cursor(commit=True) as cursor:
        _require_comment_board_writer(cursor, comment_id, member_id)
        if not repository.update_comment(
            cursor, comment_id, body, member_id, is_anonymous
        ):
            _raise_comment_permission(cursor, comment_id)
        return _comment_detail(cursor, comment_id, member_id)


# 댓글 및 대댓글 삭제 시 XP 회수
def delete_comment(comment_id: int, member_id: int) -> None:
    with db_cursor(commit=True) as cursor:
        _require_comment_board_writer(cursor, comment_id, member_id)

        # 1. 댓글 논리 삭제
        if not repository.delete_comment(cursor, comment_id, member_id):
            _raise_comment_permission(cursor, comment_id)

        # 2. 댓글 작성 XP 회수
        revoke_xp(cursor, member_id, "COMMENT", comment_id)
