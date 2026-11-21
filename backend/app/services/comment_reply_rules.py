"""답글 대상 댓글 검증 규칙(Issue #153). 게시판·취업(psycopg2)과 모임(SQLAlchemy)이 함께 쓴다.

DB 접근 방식이 달라도 같은 오류 코드·문구로 판단하도록 조회 결과(매핑)만 받아 검사한다.
"""

from collections.abc import Mapping

from fastapi import HTTPException


def decide_reply_root(post_id: int, parent_comment_id: int | None, target: Mapping | None) -> int:
    """답글 대상(target)을 검증하고 저장할 최상위 원댓글 ID를 돌려준다.

    target: 삭제되지 않은 대상 댓글 조회 결과. 없거나 삭제됐으면 None.
        키: comment_id, post_id, parent_comment_id, root_post_id, root_parent_comment_id
        (root_*는 대상이 대댓글일 때 그 원댓글의 값, 원댓글이면 None)
    - 대상이 없거나 삭제됨 → 404
    - 다른 게시글의 댓글 → 422
    - 대상의 원댓글이 다른 게시글이거나 다시 부모가 있음(깨진 스레드) → 422
    - 함께 보낸 parent_comment_id가 계산한 원댓글과 다름 → 422
    원댓글은 서버가 정하므로 항상 2단계(원댓글 → 답글)로 저장된다.
    """
    if target is None:
        raise HTTPException(status_code=404, detail="답글 대상 댓글을 찾을 수 없습니다.")
    if target["post_id"] != post_id:
        raise HTTPException(
            status_code=422,
            detail="같은 게시글의 댓글에만 답글을 작성할 수 있습니다.",
        )

    root_comment_id = target["parent_comment_id"] or target["comment_id"]
    # 대상이 대댓글이면 그 원댓글이 같은 게시글의 최상위 댓글이어야 한다(3단계 이상 데이터 차단).
    if target["parent_comment_id"] is not None and (
        target["root_post_id"] != post_id or target["root_parent_comment_id"] is not None
    ):
        raise HTTPException(status_code=422, detail="답글 대상 댓글의 스레드 정보가 올바르지 않습니다.")

    if parent_comment_id is not None and parent_comment_id != root_comment_id:
        raise HTTPException(
            status_code=422,
            detail="parent_comment_id와 reply_to_comment_id가 같은 댓글 스레드를 가리키지 않습니다.",
        )
    return root_comment_id
