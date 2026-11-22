"""댓글·대댓글 작성 후 Discord DM 알림 대기 행(notifications)을 저장한다.

게시판·모임·취업 댓글 Service가 댓글 커밋이 끝난 뒤 호출한다. 알림은 댓글과 별도
트랜잭션이므로 저장에 실패해도 댓글 작성 결과는 바뀌지 않는다 (호출 측에서 예외를 기록).
Discord Bot이 status='PENDING' 행을 polling해 DM을 보내고 상태를 바꾼다.
"""

# db_cursor : 알림 INSERT 한 건을 자체 트랜잭션으로 커밋함.
from app.core.db_connect import db_cursor


def save_comment_notification(
    post_id: int,
    comment_id: int,
    actor_member_id: int,
    parent_comment_id: int | None = None,
) -> int:
    """새 댓글 한 건에 대한 알림을 저장하고 저장한 행 수(0 또는 1)를 반환한다.

    - 일반 댓글(COMMENT): 받는 사람 = 게시글 작성자
    - 답글(REPLY): 받는 사람 = 실제 답글 대상 댓글 작성자 (Issue #153)
      대상 = reply_to_comment_id, 기존 데이터(NULL)는 parent_comment_id(원댓글)
      원댓글 작성자와 대상 작성자가 달라도 대상 작성자 한 명에게만 보낸다.
      익명 댓글도 내부 회원 ID(author_member_id)로 받는 사람을 찾는다. 이 값은 API로 나가지 않는다.

    저장된 댓글 행을 기준으로 받는 사람과 종류를 판단하고, 전달받은 값은 일치 확인에만 쓴다.
    대상 댓글은 같은 게시글이면서 원댓글 자신이거나 같은 원댓글 아래 답글이어야 한다.
    아래 경우에는 행을 만들지 않는다 (0 반환).
    - 본인 글에 단 댓글, 본인 댓글에 단 답글
    - 댓글·게시글·답글 대상 댓글이 없거나 삭제됨, 전달값이 저장된 댓글과 다름
    - 저장된 답글 관계가 스레드 규칙과 맞지 않음 (다른 게시글·다른 스레드·3단계 이상)
    - 작성자 또는 받는 사람이 실제 회원이 아님 (member_id <= 0, 관리자·임시 ID)
    - 받는 사람이 탈퇴 회원 (DM 수신 정보가 비식별화되어 있음)
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
                        ELSE reply_target.author_member_id
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
                -- 원댓글: 같은 게시글의 최상위 댓글이어야 함 (삭제된 자리표시여도 됨)
                LEFT JOIN comments AS root
                    ON root.comment_id = c.parent_comment_id
                    AND root.post_id = c.post_id
                    AND root.parent_comment_id IS NULL
                -- 실제 답글 대상: 기존 데이터(NULL)는 원댓글. 살아 있고 같은 스레드여야 함
                LEFT JOIN comments AS reply_target
                    ON reply_target.comment_id = COALESCE(c.reply_to_comment_id, c.parent_comment_id)
                    AND reply_target.post_id = c.post_id
                    AND reply_target.deleted_at IS NULL
                    AND (
                        reply_target.comment_id = c.parent_comment_id
                        OR reply_target.parent_comment_id = c.parent_comment_id
                    )
                WHERE c.comment_id = %(comment_id)s
                    AND c.post_id = %(post_id)s
                    AND c.author_member_id = %(actor_member_id)s
                    AND c.parent_comment_id IS NOT DISTINCT FROM %(parent_comment_id)s
                    AND c.deleted_at IS NULL
                    -- 답글은 올바른 원댓글과 살아 있는 답글 대상이 있어야 함
                    AND (
                        c.parent_comment_id IS NULL
                        OR (root.comment_id IS NOT NULL AND reply_target.comment_id IS NOT NULL)
                    )
            ) AS target
            JOIN members AS receiver
                ON receiver.member_id = target.receiver_member_id
                AND receiver.member_status IS DISTINCT FROM 'WITHDRAWN'
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
