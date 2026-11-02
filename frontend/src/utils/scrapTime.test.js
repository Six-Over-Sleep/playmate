// node --test src/utils/scrapTime.test.js  (실행 환경 시간대와 무관해야 하므로 TZ를 바꿔 여러 번 실행한다)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { formatKstDateTime, parseServerTime } from './scrapTime.js'

test('시간대 없는 DB 시각은 UTC로 보고 한국 시간으로 표시한다', () => {
  assert.equal(formatKstDateTime('2026-11-02T01:44:41.577347'), '2026-11-02 10:44')
  assert.equal(formatKstDateTime('2026-11-02 01:44:41'), '2026-11-02 10:44')  // 공백 구분
  assert.equal(formatKstDateTime('2026-11-02T01:44'), '2026-11-02 10:44')
})

test('날짜·월·연도 경계를 넘는다', () => {
  assert.equal(formatKstDateTime('2026-11-01T15:30:00'), '2026-11-02 00:30')
  assert.equal(formatKstDateTime('2026-10-31T15:00:00'), '2026-11-01 00:00')
  assert.equal(formatKstDateTime('2026-12-31T15:00:00.000001'), '2027-01-01 00:00')
  assert.equal(formatKstDateTime('2026-11-01T14:59:59'), '2026-11-01 23:59')  // 경계 직전은 같은 날
})

test('시간대가 있는 값은 그 시간대를 따른다', () => {
  assert.equal(formatKstDateTime('2026-11-02T01:44:00Z'), '2026-11-02 10:44')
  assert.equal(formatKstDateTime('2026-11-02T10:44:00+09:00'), '2026-11-02 10:44')
  assert.equal(formatKstDateTime('2026-11-02T01:44:00+0000'), '2026-11-02 10:44')
  assert.equal(formatKstDateTime('2026-11-01T20:44:00-05:00'), '2026-11-02 10:44')
})

test('값이 없거나 잘못되면 기존과 같은 안내 문구', () => {
  assert.equal(formatKstDateTime(null), '날짜 정보 없음')
  assert.equal(formatKstDateTime(''), '날짜 정보 없음')
  assert.equal(formatKstDateTime('not-a-date'), '날짜 정보 없음')
  assert.ok(Number.isNaN(parseServerTime(undefined)))
})

test('정렬용 시각: 같은 기준(UTC)의 문자열 순서를 보존하고 같은 시각은 같다', () => {
  const values = [
    '2026-11-02T01:44:41.577347',
    '2026-11-02T01:44:41.577',
    '2026-11-02T01:44:41.5',
    '2026-11-02T01:44:41',
    '2026-11-01T15:30:00',
  ]
  const times = values.map(parseServerTime)
  for (let i = 1; i < times.length; i += 1) assert.ok(times[i - 1] >= times[i], values[i])
  assert.equal(parseServerTime('2026-11-02T01:44:41.577347'), parseServerTime('2026-11-02T01:44:41.577999'))  // 밀리초까지 같음
  assert.equal(parseServerTime('2026-11-02T01:44:41'), parseServerTime('2026-11-02T10:44:41+09:00'))
  // 시간대 없는 값(UTC)과 오프셋 값이 섞여도 실제 시각 순서
  assert.ok(parseServerTime('2026-11-02T01:00:00') > parseServerTime('2026-11-02T09:30:00+09:00'))
})
