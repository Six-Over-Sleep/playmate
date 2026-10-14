"""게시판 업무 순서·권한·트랜잭션을 관리한다."""

from typing import Any

from fastapi import HTTPException
from psycopg2 import errors

from app.core.db_connect import db_cursor
from app.repositories import board_repository as repository


def _require_board(cursor, board_id: int) -> dict[str, Any]:
    """게시판을 조회하고 없으면 기존 404 응답으로 처리한다."""
    board = repository.get_board(cursor, board_id)
    if board is None:
        raise HTTPException(status_code=404, detail="게시판을 찾을 수 없습니다.")
    return board


def _require_post(cursor, board_id: int, post_id: int) -> None:
    """댓글 처리에 필요한 게시글 존재 여부만 검증한다."""
    if not repository.post_exists(cursor, board_id, post_id):
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")


def _post_detail(cursor, board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    """같은 트랜잭션에서 게시글 응답을 구성하고 누락 시 404를 발생시킨다."""
    post = repository.get_post(cursor, board_id, post_id, member_id)
    if post is None:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    return post


def _comment_detail(cursor, comment_id: int, member_id: int) -> dict[str, Any]:
    """같은 트랜잭션에서 댓글 응답을 구성하고 누락 시 404를 발생시킨다."""
    comment = repository.get_comment(cursor, comment_id, member_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
    return comment


def list_boards() -> list[dict[str, Any]]:
    """기본 게시판을 우선하는 기존 순서로 게시판 목록을 반환한다."""
    with db_cursor() as cursor:
        return repository.list_boards(cursor)


def create_board(
    name: str, description: str | None, creation_reason: str | None, member_id: int
) -> dict[str, Any]:
    """게시판 저장·응답 조회를 한 트랜잭션으로 처리한다. 이름 중복은 409이다."""
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


def get_board(board_id: int) -> dict[str, Any]:
    """게시판 ID의 상세를 반환한다. 없으면 404이다."""
    with db_cursor() as cursor:
        return _require_board(cursor, board_id)


def list_posts(
    board_id: int, q: str | None, sort: str, member_id: int
) -> list[dict[str, Any]]:
    """게시판 확인 후 검색 목록을 반환한다. 기존 latest 정렬만 허용한다.

    q는 공백을 제거하고 member_id는 작성자 표시 계산에 사용한다.
    게시판·목록·이미지 조회는 한 연결을 사용하며 이미지 N+1을 방지한다.
    """
    if sort != "latest":
        raise HTTPException(status_code=422, detail="sort는 latest만 지원합니다.")
    with db_cursor() as cursor:
        _require_board(cursor, board_id)
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
    """
    with db_cursor(commit=True) as cursor:
        _require_board(cursor, board_id)
        post_id = repository.create_post(
            cursor, board_id, title, body, member_id, images
        )
        return _post_detail(cursor, board_id, post_id, member_id)


def get_post(board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    """게시판·게시글 ID의 상세를 반환한다. 삭제·모임 게시글은 404이다."""
    with db_cursor() as cursor:
        return _post_detail(cursor, board_id, post_id, member_id)


def _raise_post_permission(cursor, board_id: int, post_id: int) -> None:
    """변경 실패 시 존재하는 글은 403, 없는 글은 404로 구분한다."""
    _require_post(cursor, board_id, post_id)
    raise HTTPException(
        status_code=403, detail="작성자만 수정하거나 삭제할 수 있습니다."
    )


def update_post(
    board_id: int, post_id: int, title: str, body: str, member_id: int
) -> dict[str, Any]:
    """작성자 조건으로 수정 후 응답을 조회한다. 실패 시 전체 롤백한다."""
    with db_cursor(commit=True) as cursor:
        if not repository.update_post(
            cursor, board_id, post_id, title, body, member_id
        ):
            _raise_post_permission(cursor, board_id, post_id)
        return _post_detail(cursor, board_id, post_id, member_id)


def delete_post(board_id: int, post_id: int, member_id: int) -> None:
    """작성자의 글을 논리 삭제한다. 권한 실패는 403/404로 구분한다."""
    with db_cursor(commit=True) as cursor:
        if not repository.delete_post(cursor, board_id, post_id, member_id):
            _raise_post_permission(cursor, board_id, post_id)


def list_comments(board_id: int, post_id: int, member_id: int) -> list[dict[str, Any]]:
    """게시글 확인 후 댓글을 반환한다. 불필요한 상세·이미지 조회를 생략한다."""
    with db_cursor() as cursor:
        _require_post(cursor, board_id, post_id)
        return repository.list_comments(cursor, post_id, member_id)


def create_comment(
    board_id: int, post_id: int, body: str, member_id: int
) -> dict[str, Any]:
    """게시글 확인·댓글 저장·응답 조회를 한 트랜잭션에서 수행한다."""
    with db_cursor(commit=True) as cursor:
        _require_post(cursor, board_id, post_id)
        comment_id = repository.create_comment(cursor, post_id, body, member_id)
        return _comment_detail(cursor, comment_id, member_id)


def get_comment(comment_id: int, member_id: int) -> dict[str, Any]:
    """댓글 상세를 반환한다. 없거나 삭제된 댓글은 404이다."""
    with db_cursor() as cursor:
        return _comment_detail(cursor, comment_id, member_id)


def _raise_comment_permission(cursor, comment_id: int) -> None:
    """댓글 변경 실패를 작성자 권한 부족과 데이터 누락으로 구분한다."""
    if repository.comment_exists(cursor, comment_id):
        raise HTTPException(
            status_code=403, detail="작성자만 수정하거나 삭제할 수 있습니다."
        )
    raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")


def update_comment(comment_id: int, body: str, member_id: int) -> dict[str, Any]:
    """작성자 댓글을 수정하고 같은 트랜잭션에서 응답을 조회한다."""
    with db_cursor(commit=True) as cursor:
        if not repository.update_comment(cursor, comment_id, body, member_id):
            _raise_comment_permission(cursor, comment_id)
        return _comment_detail(cursor, comment_id, member_id)


def delete_comment(comment_id: int, member_id: int) -> None:
    """작성자 댓글을 논리 삭제한다. 권한 실패는 403/404로 구분한다."""
    with db_cursor(commit=True) as cursor:
        if not repository.delete_comment(cursor, comment_id, member_id):
            _raise_comment_permission(cursor, comment_id)
