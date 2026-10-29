"""관리자 API 업무 및 트랜잭션 관리. 권한은 모든 요청에서 DB로 재검증한다."""

from fastapi import HTTPException
from backend.app.core.db_connect import db_cursor
from backend.app.repositories import admin_repository as repo


def assert_admin(member_id: int) -> None:
    with db_cursor(read_only=True) as cursor:
        if not repo.is_admin(cursor, member_id):
            raise HTTPException(status_code=403, detail="관리자 권한이 없습니다.")


def dashboard() -> dict:
    with db_cursor(read_only=True) as cursor:
        return repo.get_dashboard(cursor)


def notices() -> list[dict]:
    with db_cursor(read_only=True) as cursor:
        return repo.list_notices(cursor)


def create_notice(member_id: int, title: str, body: str) -> dict:
    with db_cursor(commit=True) as cursor:
        board_id = repo.get_notice_board_id(cursor)
        if board_id is None:
            raise HTTPException(status_code=409, detail="공지사항 게시판을 먼저 생성해주세요.")
        post_id = repo.create_notice(cursor, board_id, member_id, title, body)
        return repo.get_notice(cursor, post_id)


def update_notice(post_id: int, title: str, body: str) -> dict:
    with db_cursor(commit=True) as cursor:
        if not repo.update_notice(cursor, post_id, title, body):
            raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
        return repo.get_notice(cursor, post_id)


def delete_notice(post_id: int) -> None:
    with db_cursor(commit=True) as cursor:
        if not repo.delete_notice(cursor, post_id):
            raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")


def board_posts(search: str) -> list[dict]:
    with db_cursor(read_only=True) as cursor:
        return repo.list_board_posts(cursor, search)


def change_post_visibility(post_id: int, hidden: bool) -> None:
    with db_cursor(commit=True) as cursor:
        if not repo.set_post_hidden(cursor, post_id, hidden):
            raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")


def members() -> list[dict]:
    with db_cursor(read_only=True) as cursor:
        return repo.list_members(cursor)
