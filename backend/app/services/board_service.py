"""게시판 업무 순서·권한·트랜잭션을 관리한다."""

# Any : 반환되는 DB 데이터(딕셔너리)의 값 타입을 유연하게 표현함.
from typing import Any

# HTTPException : API 요청 처리 중 HTTP 오류 응답을 발생시킴.
from fastapi import HTTPException
# errors : PostgreSQL 제약조건 위반 등의 DB 오류를 구분함.
from psycopg2 import errors

# db_cursor : DB 커서를 생성하고 조회/저장 트랜잭션을 관리함.
from backend.app.core.db_connect import db_cursor
# repository : 게시판·게시글·댓글에 대한 실제 SQL 실행을 담당함.
from backend.app.repositories import board_repository as repository
import logging
from backend.app.services.xp_service import grant_xp, revoke_xp


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


def _require_post(cursor, board_id: int, post_id: int) -> None:
    """댓글 처리에 필요한 게시글 존재 여부만 검증한다."""
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
def list_boards() -> list[dict[str, Any]]:
    """기본 게시판을 우선하는 기존 순서로 게시판 목록을 반환한다."""
    # read_only=True : 조회용 트랜잭션으로 DB 작업을 수행함.
    with db_cursor(read_only=True) as cursor:
        return repository.list_boards(cursor)



def create_post(
    board_id: int,
    title: str,
    body: str,
    member_id: int,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:

    # 1. 게시글 저장
    with db_cursor(commit=True) as cursor:
        _require_board(cursor, board_id)

        post_id = repository.create_post(
            cursor, board_id, title, body, member_id, images
        )

        post = _post_detail(
            cursor, board_id, post_id, member_id
        )

    # 2. 게시글 커밋 성공 후 XP 지급
    # 관리자(-1)는 제외
    if member_id > 0:
        try:
            grant_xp(member_id, "POST", post_id)
        except Exception:
            logger.exception(
                "게시글 XP 지급 실패: post_id=%s",
                post_id
            )

    # 3. 생성된 게시글 반환
    return post



def get_board(board_id: int) -> dict[str, Any]:
    """게시판 ID의 상세를 반환한다. 없으면 404이다."""
    with db_cursor(read_only=True) as cursor:
        return _require_board(cursor, board_id)


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
        # 게시판이 없으면 목록 조회 전에 404 오류를 발생시킴.
        _require_board(cursor, board_id)
        # 검색어가 없으면 빈 문자열 사용, 있으면 양쪽 공백 제거 후 조회함.
        return repository.list_posts(cursor, board_id, (q or "").strip(), member_id)


def create_post(
    board_id: int,
    title: str,
    body: str,
    member_id: int,
    images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """게시판 확인→게시글·이미지 저장→응답 조회→커밋 순서로 처리한다.

    images는 업로드 모듈에서 검증한 메타데이터이다. 응답 조회 실패도 롤백하므로
    라우터가 실패 파일을 정리할 때 이미 커밋된 이미지 참조를 삭제하지 않는다.
    커밋 응답이 끊겨 성공 여부가 불명확한 경우에는 업로드 파일을 보존한다.
    """
    # 게시글과 첨부 이미지 메타데이터를 같은 DB 트랜잭션으로 저장함.
    with db_cursor(commit=True) as cursor:
        # 유효한 게시판인지 확인함.
        _require_board(cursor, board_id)
        # 게시글 및 이미지 메타데이터를 저장하고 게시글 ID를 받음.
        post_id = repository.create_post(
            cursor, board_id, title, body, member_id, images
        )
        # 저장한 게시글의 응답 조회까지 성공해야 커밋이 완료됨.
        return _post_detail(cursor, board_id, post_id, member_id)


def get_post(board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    """게시판·게시글 ID의 상세를 반환한다. 삭제·모임 게시글은 404이다."""
    with db_cursor(read_only=True) as cursor:
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
    board_id: int, post_id: int, title: str, body: str, member_id: int
) -> dict[str, Any]:
    """작성자 조건으로 수정 후 응답을 조회한다. 실패 시 전체 롤백한다."""
    with db_cursor(commit=True) as cursor:
        # Repository에서 작성자 ID와 게시글 상태를 조건으로 수정함.
        # 수정된 행이 없으면 권한 부족(403) 또는 글 없음(404)을 판별함.
        if not repository.update_post(
            cursor, board_id, post_id, title, body, member_id
        ):
            _raise_post_permission(cursor, board_id, post_id)
        # 수정된 게시글을 다시 조회하여 응답으로 반환함.
        return _post_detail(cursor, board_id, post_id, member_id)



# 게시글 삭제 및 XP 회수
def delete_post(board_id: int, post_id: int, member_id: int) -> None:
    with db_cursor(commit=True) as cursor:

        # 1. 게시글 논리 삭제
        if not repository.delete_post(cursor, board_id, post_id, member_id):
            _raise_post_permission(cursor, board_id, post_id)

        # 2. 게시글 작성 XP 회수
        revoke_xp(cursor, member_id, "POST", post_id)


# =========================================================
# 5. 댓글 목록·생성·상세 조회
# =========================================================
def list_comments(board_id: int, post_id: int, member_id: int) -> list[dict[str, Any]]:
    """게시글 확인 후 댓글을 반환한다. 불필요한 상세·이미지 조회를 생략한다."""
    with db_cursor(read_only=True) as cursor:
        # 댓글이 속한 게시글이 실제로 존재하는지 확인함.
        _require_post(cursor, board_id, post_id)
        # 삭제되지 않은 댓글 목록을 조회함.
        return repository.list_comments(cursor, post_id, member_id)




# 댓글 및 대댓글 작성
def create_comment(
    board_id: int,
    post_id: int,
    body: str,
    member_id: int,
    parent_comment_id: int | None = None
) -> dict[str, Any]:

    with db_cursor(commit=True) as cursor:
        # 1. 게시글 존재 확인
        _require_post(cursor, board_id, post_id)

        # 2. 대댓글이면 부모 댓글 검증
        if parent_comment_id is not None:
            cursor.execute(
                """
                SELECT post_id, parent_comment_id
                FROM comments
                WHERE comment_id = %s
                  AND deleted_at IS NULL
                """,
                (parent_comment_id,)
            )

            parent = cursor.fetchone()

            if parent is None:
                raise HTTPException(
                    status_code=404,
                    detail="부모 댓글을 찾을 수 없습니다."
                )

            # 다른 게시글의 댓글에는 답글 작성 불가
            if parent["post_id"] != post_id:
                raise HTTPException(
                    status_code=422,
                    detail="같은 게시글의 댓글에만 답글을 작성할 수 있습니다."
                )

            # 대댓글에 다시 답글 작성 불가
            if parent["parent_comment_id"] is not None:
                raise HTTPException(
                    status_code=422,
                    detail="대댓글에는 답글을 작성할 수 없습니다."
                )

        # 3. 댓글 또는 대댓글 저장
        comment_id = repository.create_comment(
            cursor,
            post_id,
            body,
            member_id,
            parent_comment_id
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

    return comment


def get_comment(comment_id: int, member_id: int) -> dict[str, Any]:
    """댓글 상세를 반환한다. 없거나 삭제된 댓글은 404이다."""
    with db_cursor(read_only=True) as cursor:
        return _comment_detail(cursor, comment_id, member_id)


# =========================================================
# 6. 댓글 수정·삭제 및 작성자 권한 확인
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


def update_comment(comment_id: int, body: str, member_id: int) -> dict[str, Any]:
    """작성자 댓글을 수정하고 같은 트랜잭션에서 응답을 조회한다."""
    with db_cursor(commit=True) as cursor:
        # 댓글 작성자와 삭제 상태를 확인하여 본문을 수정함.
        if not repository.update_comment(cursor, comment_id, body, member_id):
            _raise_comment_permission(cursor, comment_id)
        # 변경된 댓글 정보를 다시 조회하여 반환함.
        return _comment_detail(cursor, comment_id, member_id)


# 댓글 및 대댓글 삭제 시 XP 회수
def delete_comment(comment_id: int, member_id: int) -> None:
    with db_cursor(commit=True) as cursor:

        # 1. 댓글 논리 삭제
        if not repository.delete_comment(cursor, comment_id, member_id):
            _raise_comment_permission(cursor, comment_id)

        # 2. 댓글 작성 XP 회수
        revoke_xp(cursor, member_id, "COMMENT", comment_id)
