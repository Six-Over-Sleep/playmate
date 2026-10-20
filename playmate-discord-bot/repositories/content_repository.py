"""HOT PLAYMATE 콘텐츠 저장소 경계.

구현된 것 (실제 테이블만 사용):
    - 게시판 글 1건 조회: posts + boards + comments 개수.
      Backend 게시판 API와 같은 기준이다: 삭제되지 않았고 recruits에 연결되지 않은 글.
    - 모임 1건 조회: recruits + posts + JOINED 참여자 수 (Backend /count와 같은 기준).

아직 연결하지 않은 것:
    - 자동 HOT 후보 조회. 점수와 최소 조건에 좋아요 수가 필요한데 좋아요 스키마가 아직 없다.
      좋아요 테이블/컬럼을 가정하지 않고, 연결 전까지는 후보 없음([])을 돌려준다.
      연결할 때는 hot_content_service.HotCandidate 모양으로 돌려주면 된다.
"""
from datetime import datetime
from typing import Any, Protocol

from repositories.db import Database


class ContentRepository(Protocol):
    def get_board_post(self, post_id: int) -> dict[str, Any] | None: ...
    def get_recruit(self, recruit_id: int) -> dict[str, Any] | None: ...
    def list_board_candidates(self, since: datetime) -> list[Any]: ...
    def list_recruit_candidates(self, since: datetime) -> list[Any]: ...


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

    def list_board_candidates(self, since: datetime) -> list[Any]:
        """좋아요 스키마 연결 전: 자동 후보 없음."""
        return []

    def list_recruit_candidates(self, since: datetime) -> list[Any]:
        """좋아요 스키마 연결 전: 자동 후보 없음."""
        return []
