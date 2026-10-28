"""댓글·대댓글 작성 후 Discord DM 알림 대기 행(notifications)을 저장한다.

게시판·모임·취업 댓글 Service가 댓글 커밋이 끝난 뒤 호출한다. 알림은 댓글과 별도
트랜잭션이므로 저장에 실패해도 댓글 작성 결과는 바뀌지 않는다 (호출 측에서 예외를 기록).
Discord Bot이 status='PENDING' 행을 polling해 DM을 보내고 상태를 바꾼다.
"""

# db_cursor : 알림 INSERT 한 건을 자체 트랜잭션으로 커밋함.
from backend.app.core.db_connect import db_cursor


def save_comment_notification(
    post_id: int,
    comment_id: int,
    actor_member_id: int,
    parent_comment_id: int | None = None,
) -> int:
    """새 댓글 한 건에 대한 알림을 저장하고 저장한 행 수(0 또는 1)를 반환한다.

    - 일반 댓글(COMMENT): 받는 사람 = 게시글 작성자
    - 대댓글(REPLY): 받는 사람 = 부모 댓글 작성자

    저장된 댓글 행을 기준으로 받는 사람과 종류를 판단하고, 전달받은 값은 일치 확인에만 쓴다.
    아래 경우에는 행을 만들지 않는다 (0 반환).
    - 본인 글에 단 댓글, 본인 댓글에 단 대댓글
    - 댓글·게시글·부모 댓글이 없거나 삭제됨, 전달값이 저장된 댓글과 다름
    - 작성자 또는 받는 사람이 실제 회원이 아님 (member_id <= 0, 관리자·임시 ID)
    - 같은 댓글로 이미 저장된 알림이 있음 (중복 방지)
    status는 DB 기본값 PENDING을 사용한다.
    """
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            INSERT INTO notifications (
                receiver_member_id,
                actor_member_id,
                notification_type,
                post_id,
                comment_id
            )
            SELECT
                target.receiver_member_id,
                target.actor_member_id,
                target.notification_type,
                target.post_id,
                target.comment_id
            FROM (
                SELECT
                    CASE
                        WHEN c.parent_comment_id IS NULL THEN p.author_member_id
                        ELSE parent.author_member_id
                    END AS receiver_member_id,
                    c.author_member_id AS actor_member_id,
                    CASE
                        WHEN c.parent_comment_id IS NULL THEN 'COMMENT'
                        ELSE 'REPLY'
                    END AS notification_type,
                    c.post_id,
                    c.comment_id
                FROM comments AS c
                JOIN posts AS p
                    ON p.post_id = c.post_id
                    AND p.deleted_at IS NULL
                LEFT JOIN comments AS parent
                    ON parent.comment_id = c.parent_comment_id
                    AND parent.deleted_at IS NULL
                WHERE c.comment_id = %(comment_id)s
                    AND c.post_id = %(post_id)s
                    AND c.author_member_id = %(actor_member_id)s
                    AND c.parent_comment_id IS NOT DISTINCT FROM %(parent_comment_id)s
                    AND c.deleted_at IS NULL
                    -- 대댓글은 살아 있는 부모 댓글이 있어야 함
                    AND (c.parent_comment_id IS NULL OR parent.comment_id IS NOT NULL)
            ) AS target
            WHERE target.receiver_member_id > 0
                AND target.actor_member_id > 0
                AND target.receiver_member_id <> target.actor_member_id
                AND NOT EXISTS (
                    SELECT 1
                    FROM notifications AS n
                    WHERE n.comment_id = target.comment_id
                )
            """,
            {
                "post_id": post_id,
                "comment_id": comment_id,
                "actor_member_id": actor_member_id,
                "parent_comment_id": parent_comment_id,
            },
        )
        return cursor.rowcount
