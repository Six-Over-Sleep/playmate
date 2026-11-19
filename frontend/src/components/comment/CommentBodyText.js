// 댓글 본문 앞에 답글 대상(@닉네임)을 붙여 표시한다 (Issue #153). 게시판·취업·모임 댓글이 함께 사용한다.
// @표시와 본문 사이에 실제 공백 문자를 넣어 복사·스크린리더에서도 구분되게 한다.
// 공백과 @표시는 화면에만 있고 comment.body(서버 저장값)는 바꾸지 않는다.
// node --test로 렌더링을 검사할 수 있도록 JSX 대신 createElement를 사용한다.
import { createElement, Fragment } from 'react'

import { MENTION_SEPARATOR, replyMention } from '../../utils/commentReply.js'

export default function CommentBodyText({ comment }) {
  const mention = replyMention(comment)
  if (!mention) return createElement(Fragment, null, comment.body)
  return createElement(
    Fragment,
    null,
    createElement(
      'span',
      { className: mention.deleted ? 'comment-mention deleted' : 'comment-mention' },
      mention.label,
    ),
    MENTION_SEPARATOR,
    comment.body,
  )
}
