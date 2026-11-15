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


# 게시글 종류(posts.post_type). 백엔드가 글을 만들 때 쓰는 값이다 (일반 BOARD, 모임 RECRUIT, 취업 CAREER).
POST_KINDS = ("BOARD", "RECRUIT", "CAREER")


def notification_post_url(base_url: str | None, post: dict[str, Any]) -> str | None:
    """알림이 가리키는 원본 게시글의 웹 주소. 종류를 확실히 알 수 없으면 추측하지 않고 None.

    입력은 알림 조회 결과의 필드다: post_id, post_type, post_board_id, recruit_id, career_category.
    종류별 근거와 주소 (프론트 경로와 같은 규칙, 위의 빌더를 그대로 쓴다):
        BOARD   : post_board_id가 있음        -> /board/{board_id}/posts/{post_id}
        RECRUIT : 모임(recruits) 행이 있음    -> /meetup/{recruit_id}   (모임 글의 상세는 post_id가 아니라 recruit_id)
        CAREER  : 취업 글(career_posts) 행이 있고 category_code가 상세 화면이 있는 값 -> /career/{category}/{post_id}
    서로 다른 종류의 근거가 함께 있거나(예: 모임 행이 있는데 게시판 ID도 있음), post_type과 근거가 다르면 주소를 만들지 않는다.
    그러면 한 글이 다른 종류의 상세 페이지로 잘못 연결되는 일이 없다. post_type이 비어 있으면 근거가 하나뿐일 때만 쓴다.
    """
    signals = set()
    if _positive_id(post.get("post_board_id")) is not None:
        signals.add("BOARD")
    if _positive_id(post.get("recruit_id")) is not None:
        signals.add("RECRUIT")
    if post.get("career_category") is not None:
        signals.add("CAREER")
    post_type = str(post.get("post_type") or "").strip().upper()
    if post_type:
        if post_type not in POST_KINDS or signals != {post_type}:
            return None
        kind = post_type
    elif len(signals) == 1:
        kind = next(iter(signals))
    else:
        return None
    if kind == "RECRUIT":
        return recruit_url(base_url, post.get("recruit_id"))
    if kind == "CAREER":
        return career_post_url(base_url, post.get("career_category"), post.get("post_id"))
    return board_post_url(base_url, post.get("post_board_id"), post.get("post_id"))
