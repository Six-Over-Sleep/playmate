"""HOT 판정과 Discord 공유 범위 정책 (순수 상수·함수, DB/Discord/AWS에 의존하지 않는다).

HOT 판정은 웹(backend)의 기준을 **그대로** 옮긴 것이다. 새 기준을 만들지 않는다. 출처 (#159 머지 후 develop):
  backend/app/core/board_policy.py           HOT_DAYS = 7, HOT_MIN_LIKES = 10
  backend/app/repositories/board_repository.py list_featured_posts(kind="hot")
    post_reactions.reaction_type = 'LIKE' 이고 created_at >= CURRENT_TIMESTAMP - 7일 인 좋아요 수 >= 10
    p.post_type = 'BOARD' AND p.post_status = 'PUBLISHED' AND b.board_name <> '공지사항'
    AND _board_post_guard(): deleted_at IS NULL, COALESCE(post_status,'PUBLISHED') = 'PUBLISHED', recruits에 연결된 글 제외
  웹 쿼리의 LIMIT 100(featuredLimit)은 화면 표시 개수다. 후보 선정 조건이 아니므로 Discord 후보 조회에는 쓰지 않는다.
  웹 쿼리의 JOIN members는 posts.author_member_id가 NOT NULL + FK라 결과를 바꾸지 않으므로 옮기지 않는다 (테스트로 일치 확인).
테스트(tests/test_hot_share.py)가 backend 상수·공지 게시판 이름과 같은지, 실제 backend 함수와 결과가 같은지 확인한다.

Discord 공유 범위 (웹보다 엄격한 허용 목록):
  웹 _can_access_board: scope_type == 'LEGACY'면 **모든 로그인 회원이 읽을 수 있다** (course_code가 있어도 읽기는 제한 없음,
  쓰기만 과정·기수 제한). NATIONAL/INSTITUTION/PROGRAM/COHORT는 소속 인증이 필요하고, 그 밖의 값(NULL 포함)은 거부한다.
  Discord는 "모든 PlayMate 회원이 읽을 수 있는 게시판" 중에서도 과정·기수 게시판을 제외한다 (제목이 과정 내부 이야기일 수 있음):
    scope_type = 'LEGACY' (NULL은 웹도 LEGACY로 보지 않고 거부하므로 동일하게 제외. 컬럼은 NOT NULL DEFAULT 'LEGACY'다)
    AND course_code IS NULL AND cohort IS NULL
    AND institution_id IS NULL AND program_id IS NULL AND cohort_id IS NULL (LEGACY CHECK 제약이 보장하지만 이중 확인)
  read_policy는 LEGACY 게시판에서 웹이 보지 않는 값이고 기본값이 SCOPE_ONLY라 조건에 넣지 않는다.
"""
from typing import Any, Mapping

KIND_HOT = "HOT"
HOT_DAYS = 7
HOT_MIN_LIKES = 10
NOTICE_BOARD_NAME = "공지사항"
LABEL = "🔥 HOT 게시글"


def is_shareable_board(board: Mapping[str, Any]) -> bool:
    """SQL 조건을 한 번 더 확인한다 (SQL과 어긋나면 공유하지 않는다). 키가 없으면 불명확한 것으로 보고 거부한다."""
    required = ("scope_type", "course_code", "cohort", "institution_id", "program_id", "cohort_id", "board_name")
    if any(key not in board for key in required):
        return False
    return (board["scope_type"] == "LEGACY"
            and all(board[key] is None for key in ("course_code", "cohort", "institution_id", "program_id", "cohort_id"))
            and board["board_name"] != NOTICE_BOARD_NAME)


# -- SQL 조각 (repository가 쓴다) --------------------------------------------------------------------------------
# 7일 경계: 웹은 timestamp(naive) 컬럼을 CURRENT_TIMESTAMP(timestamptz)와 비교한다. 이때 PostgreSQL은 naive 값을 **웹 세션의
# TimeZone**으로 해석한다. Lambda 세션의 TimeZone은 다를 수 있으므로(career_share는 Asia/Seoul) 같은 비교를
# "기준 시각을 웹 세션 시간대의 naive 값으로 바꿔 비교"하는 식으로 바꾼다: ts::timestamptz >= X  <=>  ts >= (X AT TIME ZONE tz)
# (tz에 일광절약 시간이 없을 때 정확히 같다. UTC/Asia/Seoul 모두 해당). tz는 설정(HOT_SHARE_DB_TIMEZONE)으로 받는다.
LIKES_CTE = """
    likes AS (
        SELECT l.post_id, COUNT(*)::int AS recent_likes
          FROM public.post_reactions AS l
         WHERE l.reaction_type = 'LIKE'
           AND l.created_at >= ((%(now)s::timestamptz - make_interval(days => %(hot_days)s)) AT TIME ZONE %(db_tz)s)
         GROUP BY l.post_id
        HAVING COUNT(*) >= %(min_likes)s
    )
"""

# 웹 list_featured_posts의 게시글 조건 (_board_post_guard 포함)
WEB_HOT_POST_WHERE = """
        p.post_type = 'BOARD'
    AND p.post_status = 'PUBLISHED'
    AND b.board_name <> %(notice)s
    AND p.deleted_at IS NULL
    AND COALESCE(p.post_status, 'PUBLISHED') = 'PUBLISHED'
    AND NOT EXISTS (SELECT 1 FROM public.recruits AS r WHERE r.post_id = p.post_id)
"""

# Discord 공유 허용 게시판 (is_shareable_board와 같은 조건)
SHAREABLE_BOARD_WHERE = """
    AND b.scope_type = 'LEGACY'
    AND b.course_code IS NULL AND b.cohort IS NULL
    AND b.institution_id IS NULL AND b.program_id IS NULL AND b.cohort_id IS NULL
"""


def sql_params(now, db_tz: str) -> dict:
    return {"now": now, "hot_days": HOT_DAYS, "min_likes": HOT_MIN_LIKES, "db_tz": db_tz, "notice": NOTICE_BOARD_NAME}
