"""PlayMate 웹 상세 페이지 주소. 프론트 React Router의 실제 경로와 같아야 한다.

    게시판 글: /board/{board_id}/posts/{post_id}       (hooks/board/useBoard.js parseBoardPath)
    모임:      /meetup/{recruit_id}                     (hooks/meetup/useMeetups.js)
    취업 글:   /career/{reviews|talk|lounge|lab}/{post_id}  (pages/career/CareerPage.jsx parseCareerPath)

기본 주소(config.WEB_BASE_URL)가 없거나 ID가 올바르지 않으면 None을 돌려주고, 호출 측은 링크 없이 게시한다.
"""
from typing import Any

# 상세 화면이 있는 취업 게시판 (career_posts.category_code와 같은 값). 채용 인사이트(insights)는 글이 없다.
CAREER_CATEGORIES = ("reviews", "talk", "lounge", "lab")


def _positive_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def board_post_url(base_url: str | None, board_id: Any, post_id: Any) -> str | None:
    board_id, post_id = _positive_id(board_id), _positive_id(post_id)
    if not base_url or board_id is None or post_id is None:
        return None
    return f"{base_url}/board/{board_id}/posts/{post_id}"


def recruit_url(base_url: str | None, recruit_id: Any) -> str | None:
    recruit_id = _positive_id(recruit_id)
    if not base_url or recruit_id is None:
        return None
    return f"{base_url}/meetup/{recruit_id}"


def career_post_url(base_url: str | None, category: Any, post_id: Any) -> str | None:
    post_id = _positive_id(post_id)
    if not base_url or category not in CAREER_CATEGORIES or post_id is None:
        return None
    return f"{base_url}/career/{category}/{post_id}"
