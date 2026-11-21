// 댓글 답글 대상(@닉네임) 표시 규칙 (Issue #153). 게시판·취업·모임 댓글이 함께 사용한다.
// 이름은 서버가 내려준 표시용 값(익명·탈퇴 마스킹 적용)만 쓰고, 본문에는 붙이지 않는다.

/** @표시와 본문 사이의 화면 전용 구분 문자. 본문(body)에는 넣지 않는다. */
export const MENTION_SEPARATOR = ' '

/**
 * 답글 대상 표시 정보를 돌려준다. 표시하지 않으면 null.
 * - 원댓글, 원댓글에 바로 단 답글(대상 = 원댓글, 기존 데이터 포함)은 표시하지 않는다.
 * - 대댓글·답글을 대상으로 한 답글만 실제 대상의 이름을 표시한다.
 * - 대상이 삭제되었으면 이름 대신 안전한 문구를 표시한다.
 */
export function replyMention(comment) {
  if (!comment || comment.parent_comment_id == null || comment.reply_to_comment_id == null) return null
  if (comment.reply_to_comment_id === comment.parent_comment_id) return null
  // 삭제된 대상은 원래 이름 대신 같은 자리에 '@삭제된 댓글'을 보조 색상으로 표시한다(B안).
  if (comment.reply_to_is_deleted) return { label: '@삭제된 댓글', deleted: true }
  return { label: `@${comment.reply_to_author_name || '익명'}`, deleted: false }
}

/**
 * 수정·삭제 버튼은 서버가 판단한 작성자 본인(is_owner)에게만 보인다. 삭제된 자리표시에는 없다.
 * 게시판·취업·모임 공통. 게시판은 여기에 게시판 쓰기 권한(canReply)을 함께 요구한다.
 */
export function canManageComment(comment) {
  return Boolean(comment) && !comment.is_deleted && comment.is_owner === true
}

/** 삭제된 댓글(자리표시)에는 직접 답글을 달 수 없다. */
export function canReplyTo(comment) {
  return Boolean(comment) && !comment.is_deleted
}

/**
 * 댓글을 지운 뒤 다시 조회하지 않는 화면용. 지운 댓글을 대상으로 한 답글을 '삭제된 대상'으로 바꾼다.
 * idKey: 게시판·취업은 'id', 모임은 'comment_id'
 */
export function markReplyTargetDeleted(comments, deletedId, idKey = 'id') {
  return comments.map((item) => (
    item[idKey] !== deletedId && item.reply_to_comment_id === deletedId
      ? { ...item, reply_to_author_name: null, reply_to_is_deleted: true }
      : item
  ))
}
