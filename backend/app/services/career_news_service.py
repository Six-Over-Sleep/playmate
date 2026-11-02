"""커리어 브리핑 뉴스 조회·스크랩 업무를 처리한다 (Issue #74).

뉴스 행을 화면 응답 형식(CareerNewsItem)으로 바꾼다. 요약·해설·키워드는 데이터가 없으므로 비워 둔다.
Google News 링크는 언론사 원문 주소로 검증되지 않았으므로 original_url로 보내지 않는다.
스크랩은 기존 게시글 스크랩(post_scraps)과 같은 규칙이다: 중복 등록·없는 스크랩 취소도 성공.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.core.db_connect import db_cursor
from app.repositories import career_news_repository
from app.schemas.career_news import FIELD_NAMES


KST = ZoneInfo("Asia/Seoul")
FIELD_ORDER = list(FIELD_NAMES)


def _utc(value: datetime | None) -> datetime | None:
    """career_news 시각 컬럼(UTC 기준, 시간대 없음)을 UTC 시간대 값으로 바꾼다."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _to_item(row: dict[str, Any], field_code: str | None) -> dict[str, Any]:
    codes = sorted(row["field_codes"] or [], key=FIELD_ORDER.index)
    primary = field_code if field_code in codes else (codes[0] if codes else None)
    published = _utc(row["published_at"])
    return {
        "id": row["news_id"],
        "news_id": row["news_id"],
        "title": row["title"],
        "publisher": row["source_name"] or "",
        "published_at": published.astimezone(KST).date().isoformat() if published else None,
        "published_datetime": published,
        "category": FIELD_NAMES.get(primary, ""),
        "field_code": primary,
        "categories": [FIELD_NAMES[code] for code in codes],
        "field_codes": codes,
        "link_url": row["link_url"],
        "link_type": row["link_type"],
        "original_url": None,
        "summary": None,
        "news_type": None,
        "why_it_matters": None,
        "keywords": [],
        "study_keywords": [],
        "scrapped_by_me": row["scrapped_by_me"],
    }


def list_news(
    member_id: int,
    field_code: str | None,
    days: int,
    limit: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """최근 days일 뉴스를 최신순으로 최대 limit건 반환한다. 결과가 없으면 빈 목록이다."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).astimezone(timezone.utc).replace(tzinfo=None)
    with db_cursor(read_only=True) as cursor:
        rows = career_news_repository.list_news(cursor, member_id, since, limit, field_code)
    # 분야가 없는 뉴스는 가져오기 정책상 생기지 않지만, 응답 형식을 지키기 위해 제외한다.
    items = [_to_item(row, field_code) for row in rows if row["field_codes"]]
    return {
        "items": items,
        "count": len(items),
        "field_code": field_code,
        "days": days,
        "limit": limit,
    }


def get_news(news_id: int, member_id: int) -> dict[str, Any]:
    """뉴스 상세 한 건. 기간 제한은 없다 (마이페이지 스크랩에서 오래된 뉴스도 열 수 있도록).

    숨긴 뉴스는 내가 스크랩한 경우에만 is_hidden=true로 돌려주어 스크랩 해제를 할 수 있게 하고,
    그 밖에는 목록과 같이 404로 숨긴다.
    """
    with db_cursor(read_only=True) as cursor:
        row = career_news_repository.get_news(cursor, news_id, member_id)
    if row is None or not row["field_codes"] or (row["is_hidden"] and not row["scrapped_by_me"]):
        raise HTTPException(status_code=404, detail="뉴스를 찾을 수 없습니다.")
    return {**_to_item(row, None), "is_hidden": row["is_hidden"]}


def list_my_scraps(member_id: int, limit: int) -> dict[str, Any]:
    """내가 스크랩한 뉴스 중 최근 limit건 (스크랩 최신순). 숨긴 뉴스는 is_hidden=true로 포함한다."""
    with db_cursor(read_only=True) as cursor:
        rows = career_news_repository.list_member_scraps(cursor, member_id, limit)
    items = []
    for row in rows:
        codes = sorted(row["field_codes"] or [], key=FIELD_ORDER.index)
        published = _utc(row["published_at"])
        items.append({
            "item_type": "NEWS",
            "news_id": row["news_id"],
            "title": row["title"],
            "publisher": row["source_name"] or "",
            "category": FIELD_NAMES[codes[0]] if codes else "",
            "field_code": codes[0] if codes else None,
            "published_at": published.astimezone(KST).date().isoformat() if published else None,
            # 게시글 스크랩(post_scraps.created_at)과 같은 기준이므로 변환하지 않는다
            "scrapped_at": row["scrapped_at"],
            "is_hidden": row["is_hidden"],
        })
    return {"items": items, "count": len(items), "limit": limit}


def scrap_news(news_id: int, member_id: int) -> dict[str, Any]:
    """뉴스 확인·스크랩 저장·응답 조회를 한 트랜잭션에서 수행한다. 숨긴 뉴스는 새로 스크랩할 수 없다."""
    with db_cursor(commit=True) as cursor:
        news = career_news_repository.get_news_state(cursor, news_id)
        if news is None or news["is_hidden"]:
            raise HTTPException(status_code=404, detail="뉴스를 찾을 수 없습니다.")
        career_news_repository.scrap_news(cursor, news_id, member_id)
        return career_news_repository.get_news_scrap(cursor, news_id, member_id)


def unscrap_news(news_id: int, member_id: int) -> dict[str, Any]:
    """뉴스 스크랩을 취소한다. 스크랩이 없어도 성공하며, 숨긴 뉴스의 스크랩도 취소할 수 있다."""
    with db_cursor(commit=True) as cursor:
        if career_news_repository.get_news_state(cursor, news_id) is None:
            raise HTTPException(status_code=404, detail="뉴스를 찾을 수 없습니다.")
        career_news_repository.unscrap_news(cursor, news_id, member_id)
        return career_news_repository.get_news_scrap(cursor, news_id, member_id)
