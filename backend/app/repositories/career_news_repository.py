"""커리어 브리핑 뉴스 DB 조회·스크랩 저장 함수 (career_news, 017_career_news.sql).

트랜잭션은 career_news_service.py의 db_cursor가 담당한다. 이 파일에서는 commit/rollback하지 않는다.
뉴스는 가져오기 스크립트(database/scripts/import_career_news.py)만 저장하며, 여기서는 읽기와 스크랩만 한다.
"""

from datetime import datetime
from typing import Any


def list_news(
    cursor,
    member_id: int,
    since: datetime,
    limit: int,
    field_code: str | None = None,
) -> list[dict[str, Any]]:
    """숨기지 않은 최근 뉴스를 최신순으로 조회한다.

    발행일이 없는 뉴스는 처음 수집한 시각(first_seen_at)으로 기간·정렬을 판단한다.
    since는 UTC 기준 시각이다 (career_news 시각 컬럼과 같은 기준).
    """
    cursor.execute(
        """
        SELECT
            n.news_id,
            n.title,
            n.source_name,
            n.link_url,
            n.link_type,
            n.published_at,
            ARRAY(
                SELECT f.field_code
                FROM career_news_fields AS f
                WHERE f.news_id = n.news_id
                ORDER BY f.field_code
            ) AS field_codes,
            EXISTS (
                SELECT 1
                FROM career_news_scraps AS s
                WHERE s.news_id = n.news_id
                    AND s.member_id = %(member_id)s
            ) AS scrapped_by_me
        FROM career_news AS n
        WHERE n.hidden_at IS NULL
            AND COALESCE(n.published_at, n.first_seen_at) >= %(since)s
            AND (
                %(field_code)s::text IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM career_news_fields AS f
                    WHERE f.news_id = n.news_id
                        AND f.field_code = %(field_code)s
                )
            )
        ORDER BY COALESCE(n.published_at, n.first_seen_at) DESC, n.news_id DESC
        LIMIT %(limit)s
        """,
        {
            "member_id": member_id,
            "since": since,
            "field_code": field_code,
            "limit": limit,
        },
    )
    return cursor.fetchall()


def get_news(cursor, news_id: int, member_id: int) -> dict[str, Any] | None:
    """뉴스 한 건을 기간·숨김과 관계없이 조회한다 (숨김 처리는 서비스에서 판단). 없으면 None."""
    cursor.execute(
        """
        SELECT
            n.news_id,
            n.title,
            n.source_name,
            n.link_url,
            n.link_type,
            n.published_at,
            n.hidden_at IS NOT NULL AS is_hidden,
            ARRAY(
                SELECT f.field_code
                FROM career_news_fields AS f
                WHERE f.news_id = n.news_id
                ORDER BY f.field_code
            ) AS field_codes,
            EXISTS (
                SELECT 1
                FROM career_news_scraps AS s
                WHERE s.news_id = n.news_id
                    AND s.member_id = %(member_id)s
            ) AS scrapped_by_me
        FROM career_news AS n
        WHERE n.news_id = %(news_id)s
        """,
        {"news_id": news_id, "member_id": member_id},
    )
    return cursor.fetchone()


def list_member_scraps(cursor, member_id: int, limit: int) -> list[dict[str, Any]]:
    """회원이 스크랩한 뉴스를 스크랩 최신순으로 최대 limit건 조회한다. 숨긴 뉴스도 포함한다."""
    cursor.execute(
        """
        SELECT
            n.news_id,
            n.title,
            n.source_name,
            n.published_at,
            n.hidden_at IS NOT NULL AS is_hidden,
            ARRAY(
                SELECT f.field_code
                FROM career_news_fields AS f
                WHERE f.news_id = n.news_id
                ORDER BY f.field_code
            ) AS field_codes,
            s.created_at AS scrapped_at
        FROM career_news_scraps AS s
        JOIN career_news AS n
            ON n.news_id = s.news_id
        WHERE s.member_id = %(member_id)s
        ORDER BY s.created_at DESC, s.news_id DESC
        LIMIT %(limit)s
        """,
        {"member_id": member_id, "limit": limit},
    )
    return cursor.fetchall()


def get_news_state(cursor, news_id: int) -> dict[str, Any] | None:
    """뉴스 존재·숨김 여부를 조회한다. 없으면 None."""
    cursor.execute(
        """
        SELECT news_id, hidden_at IS NOT NULL AS is_hidden
        FROM career_news
        WHERE news_id = %s
        """,
        (news_id,),
    )
    return cursor.fetchone()


# 뉴스 스크랩 저장
def scrap_news(cursor, news_id: int, member_id: int) -> None:
    """뉴스 스크랩을 저장한다. 이미 스크랩한 뉴스는 기본키 충돌을 무시한다."""
    cursor.execute(
        """
        INSERT INTO career_news_scraps (news_id, member_id)
        VALUES (%s, %s)
        ON CONFLICT (news_id, member_id) DO NOTHING
        """,
        (news_id, member_id),
    )


# 뉴스 스크랩 취소
def unscrap_news(cursor, news_id: int, member_id: int) -> None:
    """회원의 뉴스 스크랩을 삭제한다. 스크랩이 없으면 아무것도 변경하지 않는다."""
    cursor.execute(
        """
        DELETE FROM career_news_scraps
        WHERE news_id = %s
            AND member_id = %s
        """,
        (news_id, member_id),
    )


# 스크랩 등록·취소 후 응답할 내 스크랩 여부 조회
def get_news_scrap(cursor, news_id: int, member_id: int) -> dict[str, Any]:
    """회원의 뉴스 스크랩 여부를 응답 필드로 조회한다."""
    cursor.execute(
        """
        SELECT
            %s AS news_id,
            EXISTS (
                SELECT 1
                FROM career_news_scraps AS s
                WHERE s.news_id = %s
                    AND s.member_id = %s
            ) AS scrapped_by_me
        """,
        (news_id, news_id, member_id),
    )
    return cursor.fetchone()
