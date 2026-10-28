"""/게시글추천 콘텐츠 저장소: 게시판 글 / 모임 / 취업 글 1건 조회.

대상 조건은 Backend API와 같다 (삭제 안 됨, 모집글은 게시판에서 제외, 취업 글은 post_type='CAREER').
상세 링크에 필요한 ID(board_id, recruit_id, category_code)를 함께 돌려준다.
HOT 자동 선정은 팀원이 만드는 HOT 게시판으로 옮겨져 이 저장소에는 집계 SQL이 없다.
"""
from typing import Any, Protocol

from repositories.db import Database


class ContentRepository(Protocol):
    def get_board_post(self, post_id: int) -> dict[str, Any] | None: ...
    def get_recruit(self, recruit_id: int) -> dict[str, Any] | None: ...
    def get_career_post(self, post_id: int) -> dict[str, Any] | None: ...


class PostgresContentRepository:
    def __init__(self, database: Database):
        self._db = database

    def get_board_post(self, post_id: int) -> dict[str, Any] | None:
        return self._db.execute(
            """
            SELECT p.post_id, p.board_id, b.board_name, p.title, p.body, p.created_at,
                   (SELECT COUNT(*) FROM comments c
                     WHERE c.post_id = p.post_id AND c.deleted_at IS NULL) AS comment_count
              FROM posts p
              LEFT JOIN boards b ON b.board_id = p.board_id
             WHERE p.post_id = %s
               AND p.board_id IS NOT NULL
               AND p.deleted_at IS NULL
               AND NOT EXISTS (SELECT 1 FROM recruits r WHERE r.post_id = p.post_id)
            """,
            (post_id,), fetch="one",
        )

    def get_recruit(self, recruit_id: int) -> dict[str, Any] | None:
        return self._db.execute(
            """
            SELECT r.recruit_id, r.category, r.recruit_mode, r.capacity,
                   p.title, p.body, p.created_at,
                   (SELECT COUNT(*) FROM recruit_members rm
                     WHERE rm.recruit_id = r.recruit_id AND rm.status = 'JOINED') AS member_count
              FROM recruits r
              JOIN posts p ON p.post_id = r.post_id
             WHERE r.recruit_id = %s AND p.deleted_at IS NULL
            """,
            (recruit_id,), fetch="one",
        )

    def get_career_post(self, post_id: int) -> dict[str, Any] | None:
        """취업 4종 게시판 글 (Backend career_post_exists와 같은 대상 조건). 작성자는 조회하지 않는다."""
        return self._db.execute(
            """
            SELECT p.post_id, cp.category_code, p.title, p.body, p.created_at,
                   (SELECT COUNT(*) FROM comments c
                     WHERE c.post_id = p.post_id AND c.deleted_at IS NULL) AS comment_count
              FROM posts p
              JOIN career_posts cp ON cp.post_id = p.post_id
             WHERE p.post_id = %s
               AND p.post_type = 'CAREER'
               AND p.deleted_at IS NULL
            """,
            (post_id,), fetch="one",
        )
