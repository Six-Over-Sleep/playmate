// node --test src/components/comment/CommentBodyText.test.js
// 실제 컴포넌트를 react-dom/server로 렌더링해 @표시와 본문 사이 공백, 본문 불변을 확인한다.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import CommentBodyText from './CommentBodyText.js'

function render(comment) {
  return renderToStaticMarkup(createElement('p', null, createElement(CommentBodyText, { comment })))
}

/** 브라우저의 textContent(복사·스크린리더가 읽는 글자)와 같은 값: 태그만 지운다. */
function textContent(html) {
  return html.replace(/<[^>]+>/g, '')
    .replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
}

const reply = (extra) => ({
  id: 3, parent_comment_id: 1, reply_to_comment_id: 2, reply_to_author_name: '지훈',
  reply_to_is_deleted: false, body: '어떻게 공부하셨어요?', ...extra,
})

test('@닉네임과 본문 사이에 실제 공백 문자가 들어간다', () => {
  const html = render(reply())
  assert.equal(html, '<p><span class="comment-mention">@지훈</span> 어떻게 공부하셨어요?</p>')
  assert.equal(textContent(html), '@지훈 어떻게 공부하셨어요?')
})

test('본문(body) 값은 바꾸지 않는다', () => {
  const comment = reply()
  render(comment)
  assert.equal(comment.body, '어떻게 공부하셨어요?')
})

test('@표시가 없는 댓글은 앞에 공백을 붙이지 않는다', () => {
  assert.equal(render({ id: 1, parent_comment_id: null, body: '원댓글' }), '<p>원댓글</p>')
  assert.equal(render(reply({ reply_to_comment_id: 1 })), '<p>어떻게 공부하셨어요?</p>')   // 원댓글에 바로 단 답글
})

test('익명·탈퇴·삭제 대상도 같은 공백 규칙을 쓴다', () => {
  assert.equal(textContent(render(reply({ reply_to_author_name: '익명' }))), '@익명 어떻게 공부하셨어요?')
  assert.equal(textContent(render(reply({ reply_to_author_name: '탈퇴한 사용자' }))), '@탈퇴한 사용자 어떻게 공부하셨어요?')
  const deleted = render(reply({ reply_to_author_name: null, reply_to_is_deleted: true }))
  assert.equal(deleted, '<p><span class="comment-mention deleted">@삭제된 댓글</span> 어떻게 공부하셨어요?</p>')
})

test('B안: 정상·삭제·익명 대상 모두 같은 자리에 인라인 @표시 + 공백 한 칸, body는 그대로', () => {
  const body = '안녕하세요!'
  const normal = reply({ body })
  const removed = reply({ body, reply_to_author_name: '지훈', reply_to_is_deleted: true })  // 서버가 이름을 줘도 숨김
  const anonymous = reply({ body, reply_to_author_name: '익명' })
  assert.equal(textContent(render(normal)), '@지훈 안녕하세요!')
  assert.equal(textContent(render(removed)), '@삭제된 댓글 안녕하세요!')
  assert.equal(textContent(render(anonymous)), '@익명 안녕하세요!')
  assert.ok(!render(removed).includes('지훈'))                 // 삭제 대상의 기존 닉네임 미노출
  assert.ok(render(removed).includes('class="comment-mention deleted"'))   // 회색 보조 색상 클래스
  for (const comment of [normal, removed, anonymous]) assert.equal(comment.body, body)
})

test('닉네임·본문의 HTML은 글자로만 출력한다', () => {
  const html = render(reply({ reply_to_author_name: '<b>x</b>', body: '<img src=x onerror=alert(1)>' }))
  assert.ok(!html.includes('<b>') && !html.includes('<img'))
  assert.equal(textContent(html), '@<b>x</b> <img src=x onerror=alert(1)>')
})
