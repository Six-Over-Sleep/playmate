"""HOT 게시글 Discord 메시지 본문 (순수 함수). 제목과 원문 링크, 중복 확인용 마커만 담는다.

작성자(닉네임·익명 여부), 본문, 좋아요 수, 게시판 이름은 넣지 않는다. 제목 정리·멘션 무력화·URL 검증·길이 검사·마커는
career_share.messages를 그대로 쓴다. **제목 자체도 공개 정보다**: 공유 대상 게시판은 policy.is_shareable_board로 제한한다.
"""
from career_share import messages as base

HOT_COLOR = 0xE8590C
TITLE_LIMIT = 200
AUTHOR_TEXT = "🔥 HOT 게시글"


def hot_unit_id(post_id: int) -> str:
    return f"hot-{int(post_id)}"


def post_id_of(unit_id: str) -> int | None:
    if isinstance(unit_id, str) and unit_id.startswith("hot-") and unit_id[4:].isdigit():
        return int(unit_id[4:])
    return None


def hot_payload(post: dict, url: str) -> dict:
    unit = hot_unit_id(post["post_id"])
    link = base.safe_url(url)
    embed = {
        "title": base.plain_title(post.get("title"), TITLE_LIMIT),
        "url": link,
        "color": HOT_COLOR,
        "author": {"name": AUTHOR_TEXT},
        "description": f"[{base.LINK_LABEL}]({link})",
        "footer": {"text": base.marker_for(unit)},
    }
    base._check(embed)
    return {"embeds": [embed], "allowed_mentions": dict(base.NO_MENTIONS)}
