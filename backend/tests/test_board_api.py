from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import board as routes
from app.schemas.board import BoardCreate, CommentWrite, PostWrite
from app.services import board_service

NOW = datetime.now(timezone.utc)

def board(board_id=1, name="자유게시판"):
    return {"id": board_id, "name": name, "description": "함께 이야기해요.", "created_at": NOW}

def post(post_id=1, owner=True, title="제목"):
    return {"id": post_id, "board_id": 1, "title": title, "body": "본문", "author_id": 1, "author_name": "익명 A001", "created_at": NOW, "updated_at": NOW, "comment_count": 0, "is_owner": owner}

def comment(comment_id=1, owner=True):
    return {"id": comment_id, "post_id": 1, "body": "댓글", "author_id": 1, "author_name": "익명 A001", "created_at": NOW, "updated_at": NOW, "is_owner": owner}

def test_list_boards(monkeypatch):
    monkeypatch.setattr(board_service, "list_boards", lambda: [board()])
    assert routes.list_boards(1)[0]["name"] == "자유게시판"

def test_create_board(monkeypatch):
    monkeypatch.setattr(board_service, "create_board", lambda name, description, reason, member_id: board(2, name))
    assert routes.create_board(BoardCreate(name="알고리즘 질문"), 1)["id"] == 2

def test_duplicate_board_returns_409(monkeypatch):
    def duplicate(*_): raise HTTPException(status_code=409, detail="중복")
    monkeypatch.setattr(board_service, "create_board", duplicate)
    with pytest.raises(HTTPException) as error: routes.create_board(BoardCreate(name="자유게시판"), 1)
    assert error.value.status_code == 409

@pytest.mark.parametrize("name", ["", " ", "가" * 41])
def test_invalid_board_name_returns_validation_error(name):
    with pytest.raises(ValidationError): BoardCreate(name=name)

def test_create_and_get_post(monkeypatch):
    monkeypatch.setattr(board_service, "create_post", lambda board_id, title, body, member_id, images: post(title=title))
    monkeypatch.setattr(board_service, "get_post", lambda board_id, post_id, member_id: post(post_id))
    assert board_service.create_post(1, "새 글", "본문", 1, [])["title"] == "새 글"
    assert routes.get_post(1, 1, 1)["id"] == 1

def test_search_and_latest_sort_are_forwarded(monkeypatch):
    seen = {}
    def fake(board_id, q, sort, member_id):
        seen.update(q=q, sort=sort); return [post(title="React 공부")]
    monkeypatch.setattr(board_service, "list_posts", fake)
    assert routes.list_posts(1, "React", "latest", 1)[0]["title"] == "React 공부"
    assert seen == {"q": "React", "sort": "latest"}

def test_update_and_delete_post(monkeypatch):
    monkeypatch.setattr(board_service, "update_post", lambda board_id, post_id, title, body, member_id: post(post_id, title=title))
    monkeypatch.setattr(board_service, "delete_post", lambda *args: None)
    assert routes.update_post(1, 1, PostWrite(title="수정", body="수정 본문"), 1)["title"] == "수정"
    assert routes.delete_post(1, 1, 1).status_code == 204

def test_post_permission_denied(monkeypatch):
    def denied(*_): raise HTTPException(status_code=403, detail="권한 없음")
    monkeypatch.setattr(board_service, "update_post", denied)
    with pytest.raises(HTTPException) as error: routes.update_post(1, 1, PostWrite(title="수정", body="본문"), 2)
    assert error.value.status_code == 403

def test_missing_post_returns_404(monkeypatch):
    def missing(*_): raise HTTPException(status_code=404, detail="없음")
    monkeypatch.setattr(board_service, "get_post", missing)
    with pytest.raises(HTTPException) as error: routes.get_post(1, 999, 1)
    assert error.value.status_code == 404

def test_comment_crud(monkeypatch):
    monkeypatch.setattr(board_service, "list_comments", lambda *args: [comment()])
    monkeypatch.setattr(board_service, "create_comment", lambda *args: comment())
    monkeypatch.setattr(board_service, "update_comment", lambda comment_id, body, member_id: {**comment(comment_id), "body": body})
    monkeypatch.setattr(board_service, "delete_comment", lambda *args: None)
    assert routes.list_comments(1, 1, 1)[0]["body"] == "댓글"
    assert routes.create_comment(1, 1, CommentWrite(body="댓글"), 1)["id"] == 1
    assert routes.update_comment(1, CommentWrite(body="수정 댓글"), 1)["body"] == "수정 댓글"
    assert routes.delete_comment(1, 1).status_code == 204

def test_reply_forwards_parent_comment_id(monkeypatch):
    seen = {}
    def fake(board_id, post_id, body, member_id, parent_comment_id):
        seen.update(parent_comment_id=parent_comment_id); return {**comment(5), "parent_comment_id": parent_comment_id}
    monkeypatch.setattr(board_service, "create_comment", fake)
    assert routes.create_comment(1, 1, CommentWrite(body="답글", parent_comment_id=3), 1)["parent_comment_id"] == 3
    assert seen == {"parent_comment_id": 3}

def test_update_comment_rejects_parent_change(monkeypatch):
    monkeypatch.setattr(board_service, "update_comment", lambda *args: comment())
    with pytest.raises(HTTPException) as error: routes.update_comment(1, CommentWrite(body="수정", parent_comment_id=3), 1)
    assert error.value.status_code == 422

def test_comment_permission_denied(monkeypatch):
    def denied(*_): raise HTTPException(status_code=403, detail="권한 없음")
    monkeypatch.setattr(board_service, "delete_comment", denied)
    with pytest.raises(HTTPException) as error: routes.delete_comment(1, 2)
    assert error.value.status_code == 403

def test_like_and_unlike_post(monkeypatch):
    monkeypatch.setattr(board_service, "like_post", lambda board_id, post_id, member_id: {"post_id": post_id, "like_count": 1, "liked_by_me": True})
    monkeypatch.setattr(board_service, "unlike_post", lambda board_id, post_id, member_id: {"post_id": post_id, "like_count": 0, "liked_by_me": False})
    assert routes.like_post(1, 2, 1) == {"post_id": 2, "like_count": 1, "liked_by_me": True}
    assert routes.unlike_post(1, 2, 1)["liked_by_me"] is False

def test_like_missing_post_returns_404(monkeypatch):
    def missing(*_): raise HTTPException(status_code=404, detail="없음")
    monkeypatch.setattr(board_service, "like_post", missing)
    with pytest.raises(HTTPException) as error: routes.like_post(1, 999, 1)
    assert error.value.status_code == 404

def test_scrap_and_unscrap_post(monkeypatch):
    monkeypatch.setattr(board_service, "scrap_post", lambda board_id, post_id, member_id: {"post_id": post_id, "scrapped_by_me": True})
    monkeypatch.setattr(board_service, "unscrap_post", lambda board_id, post_id, member_id: {"post_id": post_id, "scrapped_by_me": False})
    assert routes.scrap_post(1, 2, 1) == {"post_id": 2, "scrapped_by_me": True}
    assert routes.unscrap_post(1, 2, 1)["scrapped_by_me"] is False

def test_scrap_missing_post_returns_404(monkeypatch):
    def missing(*_): raise HTTPException(status_code=404, detail="없음")
    monkeypatch.setattr(board_service, "scrap_post", missing)
    with pytest.raises(HTTPException) as error: routes.scrap_post(1, 999, 1)
    assert error.value.status_code == 404

def test_openapi_declares_expected_status_codes():
    route_map = {(route.path, method): route for route in routes.router.routes for method in route.methods}
    assert route_map[("/api/boards", "POST")].status_code == 201
    assert route_map[("/api/boards/{board_id}/posts", "POST")].status_code == 201
    assert route_map[("/api/boards/{board_id}/posts/{post_id}", "DELETE")].status_code == 204
    assert route_map[("/api/comments/{comment_id}", "DELETE")].status_code == 204
    assert route_map[("/api/boards/{board_id}/posts/{post_id}/like", "PUT")].response_model.__name__ == "PostLikeResponse"
    assert route_map[("/api/boards/{board_id}/posts/{post_id}/like", "DELETE")].response_model.__name__ == "PostLikeResponse"
    assert route_map[("/api/boards/{board_id}/posts/{post_id}/scrap", "PUT")].response_model.__name__ == "PostScrapResponse"
    assert route_map[("/api/boards/{board_id}/posts/{post_id}/scrap", "DELETE")].response_model.__name__ == "PostScrapResponse"
