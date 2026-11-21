// node --test src/utils/commentReply.test.js
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { canManageComment, canReplyTo, markReplyTargetDeleted, replyMention } from './commentReply.js'

const root = { id: 1, parent_comment_id: null, reply_to_comment_id: null, reply_to_author_name: null, reply_to_is_deleted: false }

test('원댓글과 원댓글에 바로 단 답글에는 @닉네임을 표시하지 않는다', () => {
  assert.equal(replyMention(root), null)
  assert.equal(replyMention({ id: 2, parent_comment_id: 1, reply_to_comment_id: 1, reply_to_author_name: '민혁' }), null)
  // 기존 응답·구버전 서버처럼 reply_to 필드가 없어도 표시하지 않는다
  assert.equal(replyMention({ id: 2, parent_comment_id: 1 }), null)
})

test('대댓글·답글의 답글에는 실제 대상의 이름을 표시한다', () => {
  assert.deepEqual(
    replyMention({ id: 3, parent_comment_id: 1, reply_to_comment_id: 2, reply_to_author_name: '지훈', reply_to_is_deleted: false }),
    { label: '@지훈', deleted: false },
  )
  assert.deepEqual(
    replyMention({ id: 4, parent_comment_id: 1, reply_to_comment_id: 3, reply_to_author_name: '수빈', reply_to_is_deleted: false }),
    { label: '@수빈', deleted: false },
  )
})

test('익명·탈퇴 대상은 서버 마스킹 이름을, 삭제 대상은 안전한 문구를 쓴다', () => {
  assert.equal(replyMention({ parent_comment_id: 1, reply_to_comment_id: 2, reply_to_author_name: '익명' }).label, '@익명')
  assert.equal(replyMention({ parent_comment_id: 1, reply_to_comment_id: 2, reply_to_author_name: '탈퇴한 사용자' }).label, '@탈퇴한 사용자')
  assert.equal(replyMention({ parent_comment_id: 1, reply_to_comment_id: 2, reply_to_author_name: null }).label, '@익명')
  assert.deepEqual(
    replyMention({ parent_comment_id: 1, reply_to_comment_id: 2, reply_to_author_name: null, reply_to_is_deleted: true }),
    { label: '@삭제된 댓글', deleted: true },
  )
})

test('삭제된 댓글에는 답글 버튼을 두지 않는다', () => {
  assert.equal(canReplyTo(root), true)
  assert.equal(canReplyTo({ ...root, is_deleted: true }), false)
  assert.equal(canReplyTo(null), false)
})

test('수정·삭제 버튼은 작성자 본인(is_owner=true)의 살아 있는 댓글에만 보인다 (세 게시판 공통)', () => {
  assert.equal(canManageComment({ ...root, is_owner: true }), true)
  assert.equal(canManageComment({ ...root, is_owner: false }), false)          // 다른 회원 댓글
  assert.equal(canManageComment(root), false)                                   // 값이 없으면 숨김
  assert.equal(canManageComment({ ...root, is_owner: 'true' }), false)          // 불리언 true만 인정
  assert.equal(canManageComment({ ...root, is_owner: true, is_deleted: true }), false)  // 삭제 자리표시
  assert.equal(canManageComment(null), false)
})

test('지운 댓글을 대상으로 한 답글만 삭제 대상으로 바꾼다', () => {
  const rows = [
    { comment_id: 2, parent_comment_id: 1, reply_to_comment_id: 1, reply_to_author_name: '민혁', reply_to_is_deleted: false },
    { comment_id: 3, parent_comment_id: 1, reply_to_comment_id: 2, reply_to_author_name: '지훈', reply_to_is_deleted: false },
  ]
  const next = markReplyTargetDeleted(rows, 2, 'comment_id')
  assert.equal(next[0], rows[0])
  assert.deepEqual(next[1], { ...rows[1], reply_to_author_name: null, reply_to_is_deleted: true })
})
