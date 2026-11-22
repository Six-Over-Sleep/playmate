"""게시글 신고: 신고자 중복 방지, 3명 신고 시 자동 비노출, 관리자 요약 조회."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Literal

from app.core.auth import get_current_member_id
from app.core.db_connect import db_cursor
from app.services import admin_service

router = APIRouter(prefix="/api", tags=["board-reports"])
admin_router = APIRouter(prefix="/api/admin", tags=["board-reports-admin"])
from app.core.board_policy import REPORT_HIDE_COUNT as REPORT_THRESHOLD

# 045: 신고는 post_reactions(reaction_type = 'REPORT')에 저장한다.
# 아래 조회문은 기존 post_reports와 같은 컬럼 이름으로 꺼낸 이 하위 쿼리를 쓴다
# (PostgreSQL이 실행 계획에서 펼치므로 테이블을 직접 읽는 것과 비용이 같다).
_REPORTS = """(
    SELECT reaction_id AS report_id, post_id, member_id AS reporter_member_id,
           reason, details, created_at
    FROM post_reactions
    WHERE reaction_type = 'REPORT'
)"""


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: Literal["SPAM", "ABUSE", "HATE", "PRIVACY", "OTHER"]
    details: str | None = Field(default=None, max_length=500)


def submit_report(cursor, board_id: int, post_id: int, member_id: int, payload: ReportCreate) -> dict:
    """한 게시글에 대한 동시 신고도 행 잠금으로 순차 처리합니다."""
    cursor.execute(
        """
        SELECT p.post_id, p.author_member_id, p.post_status, p.deleted_at,
               p.post_type, p.source_type, b.board_name
        FROM posts p
        JOIN boards b ON b.board_id = p.board_id
        WHERE p.board_id = %s AND p.post_id = %s
        FOR UPDATE OF p
        """,
        (board_id, post_id),
    )
    post = cursor.fetchone()
    if (not post or post["deleted_at"] is not None
        or (post["post_status"] or "PUBLISHED") != "PUBLISHED"
        or post["post_type"] != "BOARD"):
        raise HTTPException(status_code=404, detail="신고할 수 있는 게시글이 없습니다.")
    # 공지/운영 시스템 공지를 다수 신고로 숨기는 악용 방지
    if post["board_name"] == "공지사항" or post["source_type"] != "USER":
        raise HTTPException(status_code=403, detail="운영 공지사항은 신고할 수 없습니다.")
    if post["author_member_id"] == member_id:
        raise HTTPException(status_code=403, detail="자신의 게시글은 신고할 수 없습니다.")

    cursor.execute(
        """
        INSERT INTO post_reactions (post_id, member_id, reaction_type, reason, details)
        VALUES (%s, %s, 'REPORT', %s, %s)
        ON CONFLICT (post_id, reaction_type, member_id) DO NOTHING
        RETURNING reaction_id AS report_id
        """,
        (post_id, member_id, payload.reason, payload.details or None),
    )
    if cursor.fetchone() is None:
        raise HTTPException(status_code=409, detail="이미 신고한 게시글입니다.")
    cursor.execute(
        "SELECT COUNT(*)::int AS count FROM post_reactions WHERE reaction_type = 'REPORT' AND post_id = %s",
        (post_id,),
    )
    count = cursor.fetchone()["count"]
    hidden = count >= REPORT_THRESHOLD
    if hidden:
        cursor.execute(
            """
            UPDATE posts SET post_status = 'HIDDEN', updated_at = CURRENT_TIMESTAMP
            WHERE post_id = %s AND post_status = 'PUBLISHED'
            """,
            (post_id,),
        )
    return {"post_id": post_id, "report_count": count, "hidden": hidden}


@router.post(
    "/boards/{board_id}/posts/{post_id}/reports",
    status_code=status.HTTP_201_CREATED,
)
def report_post(
    board_id: int,
    post_id: int,
    payload: ReportCreate,
    member_id: int = Depends(get_current_member_id),
):
    with db_cursor(commit=True) as cursor:
        return submit_report(cursor, board_id, post_id, member_id, payload)


@admin_router.get("/board-reports")
def list_reported_posts(member_id: int = Depends(get_current_member_id)):
    admin_service.assert_admin(member_id)
    with db_cursor(read_only=True) as cursor:
        cursor.execute(
            """
            SELECT p.post_id, p.board_id, p.title, p.post_status,
                   COUNT(r.report_id)::int AS report_count,
                   MAX(r.created_at)::timestamptz AS last_reported_at
            FROM """ + _REPORTS + """ AS r
            JOIN posts p ON p.post_id = r.post_id
            GROUP BY p.post_id, p.board_id, p.title, p.post_status
            ORDER BY last_reported_at DESC
            LIMIT 200
            """
        )
        return list(cursor.fetchall())

# 복구는 기존 관리자 API PATCH /api/admin/posts/{post_id}/visibility {"hidden": false} 이용

# PLAYMATE_ADMIN_REPORT_PANEL_V1
@admin_router.get("/board-reports/details")
def list_reported_posts_details(
    member_id: int = Depends(get_current_member_id),
    page: Annotated[int | None, Query(ge=1, le=100000)] = None,
    q: Annotated[str, Query(max_length=100)] = "",
    status_filter: Literal["all", "visible", "hidden"] = "all",
):
    """신고가 접수된 게시글과 신고별 사유를 관리자에게만 반환한다."""
    admin_service.assert_admin(member_id)
    if page is not None:
        return _reports_paged(page, q.strip(), status_filter)
    with db_cursor(read_only=True) as cursor:
        cursor.execute(
            """
            SELECT
                p.post_id, p.board_id, p.title,
                COALESCE(p.post_status, 'PUBLISHED') AS post_status,
                b.board_name,
                COALESCE(NULLIF(m.nickname, ''), '탈퇴 회원') AS author_name,
                p.created_at::timestamptz AS created_at,
                COUNT(r.report_id)::int AS report_count,
                MAX(r.created_at)::timestamptz AS last_reported_at
            FROM """ + _REPORTS + """ AS r
            JOIN posts AS p ON p.post_id = r.post_id
            JOIN boards AS b ON b.board_id = p.board_id
            LEFT JOIN members AS m ON m.member_id = p.author_member_id
            WHERE p.deleted_at IS NULL AND p.post_type = 'BOARD'
            GROUP BY p.post_id, p.board_id, p.title, p.post_status,
                     b.board_name, m.nickname, p.created_at
            ORDER BY last_reported_at DESC, p.post_id DESC
            LIMIT 200
            """
        )
        posts = [dict(post) for post in cursor.fetchall()]
        if not posts:
            return []

        ids = [post['post_id'] for post in posts]
        cursor.execute(
            """
            SELECT r.post_id, r.report_id, r.reason, r.details, r.created_at::timestamptz AS created_at,
                   COALESCE(NULLIF(m.nickname, ''), '탈퇴 회원') AS reporter_name
            FROM """ + _REPORTS + """ AS r
            LEFT JOIN members AS m ON m.member_id = r.reporter_member_id
            WHERE r.post_id = ANY(%s)
            ORDER BY r.created_at DESC, r.report_id DESC
            """,
            (ids,),
        )
        grouped = {post_id: [] for post_id in ids}
        for report in cursor.fetchall():
            item = dict(report)
            grouped[item.pop('post_id')].append(item)
        for post in posts:
            post['reports'] = grouped[post['post_id']]
        return posts



_REPORTS_FILTER_SQL = """
FROM """ + _REPORTS + """ AS r
JOIN posts AS p ON p.post_id = r.post_id
JOIN boards AS b ON b.board_id = p.board_id
LEFT JOIN members AS m ON m.member_id = p.author_member_id
WHERE p.deleted_at IS NULL
  AND p.post_type = 'BOARD'
  AND (
      %s = ''
      OR p.title ILIKE %s
      OR b.board_name ILIKE %s
      OR COALESCE(m.nickname, '') ILIKE %s
  )
  AND (
      %s = 'all'
      OR (%s = 'hidden' AND COALESCE(p.post_status, 'PUBLISHED') = 'HIDDEN')
      OR (%s = 'visible' AND COALESCE(p.post_status, 'PUBLISHED') <> 'HIDDEN')
  )
"""


def _reports_paged(page: int, search: str, state: str) -> dict:
    """Return filtered reported posts and their details, 20 per page."""
    size = 20
    pattern = f"%{search}%"
    params = (
        search, pattern, pattern, pattern,
        state, state, state,
    )

    with db_cursor(read_only=True) as cursor:
        cursor.execute(
            """
            SELECT
                COUNT(DISTINCT p.post_id)::int AS total,
                COUNT(DISTINCT p.post_id) FILTER (
                    WHERE COALESCE(p.post_status, 'PUBLISHED') = 'HIDDEN'
                )::int AS hidden_total,
                COUNT(r.report_id)::bigint AS report_count
            """ + _REPORTS_FILTER_SQL,
            params,
        )
        summary = dict(cursor.fetchone())

        total = int(summary["total"])
        total_pages = max(1, (total + size - 1) // size)
        current = min(page, total_pages)

        cursor.execute(
            """
            SELECT
                p.post_id, p.board_id, p.title,
                COALESCE(p.post_status, 'PUBLISHED') AS post_status,
                b.board_name,
                COALESCE(NULLIF(m.nickname, ''), 'Withdrawn member') AS author_name,
                p.created_at::timestamptz AS created_at,
                COUNT(r.report_id)::int AS report_count,
                MAX(r.created_at)::timestamptz AS last_reported_at
            """ + _REPORTS_FILTER_SQL + """
            GROUP BY p.post_id, p.board_id, p.title, p.post_status,
                     b.board_name, m.nickname, p.created_at
            ORDER BY last_reported_at DESC, p.post_id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, size, (current - 1) * size),
        )
        posts = [dict(row) for row in cursor.fetchall()]

        if posts:
            ids = [post["post_id"] for post in posts]
            cursor.execute(
                """
                SELECT r.post_id, r.report_id, r.reason, r.details,
                       r.created_at::timestamptz AS created_at,
                       COALESCE(NULLIF(m.nickname, ''), 'Withdrawn member')
                           AS reporter_name
                FROM """ + _REPORTS + """ AS r
                LEFT JOIN members AS m
                    ON m.member_id = r.reporter_member_id
                WHERE r.post_id = ANY(%s)
                ORDER BY r.created_at DESC, r.report_id DESC
                """,
                (ids,),
            )
            grouped = {post_id: [] for post_id in ids}
            for row in cursor.fetchall():
                item = dict(row)
                grouped[item.pop("post_id")].append(item)
            for post in posts:
                post["reports"] = grouped[post["post_id"]]

    return {
        "items": posts,
        "total": total,
        "page": current,
        "page_size": size,
        "total_pages": total_pages,
        "hidden_total": int(summary["hidden_total"]),
        "report_count": int(summary["report_count"]),
    }
