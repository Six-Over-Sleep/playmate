import test from 'node:test'
import assert from 'node:assert/strict'
import { validateMeetupForm, meetupErrorMessage } from './meetupForm.js'
import { createSharedMeetupRead, programAvailabilityMessage } from './meetupEditorRequests.js'

test('DB upper bounds are validated at their exact boundaries', () => {
  const base = { title: '가'.repeat(100), body: '소개', category: 'sports', capacity: 2147483647,
    place: '가'.repeat(255), sport_name: '가'.repeat(100), is_online: false, recruit_mode: 'short',
    meeting_start: '2030-01-08T18:00', meeting_end: '2030-01-08T20:00', recruit_end: '2030-01-07T18:00' }
  const opts = { program: false, now: Date.parse('2030-01-01') }
  assert.deepEqual(validateMeetupForm(base, opts), {})
  for (const [key, invalid] of Object.entries({ title: '가'.repeat(101), sport_name: '가'.repeat(101), place: '가'.repeat(256), capacity: 2147483648 })) {
    assert.ok(validateMeetupForm({ ...base, [key]: invalid }, opts)[key])
  }
})

test('StrictMode metadata consumers share one read and failed reads can retry', async () => {
  let complete, calls = 0
  const load = createSharedMeetupRead(() => { calls++; return new Promise((resolve) => { complete = resolve }) })
  const a = load(), b = load()
  assert.equal(a, b)
  await Promise.resolve()
  assert.equal(calls, 1)
  complete({ ready: true })
  assert.deepEqual(await b, { ready: true })
  let attempts = 0
  const retry = createSharedMeetupRead(() => { if (++attempts === 1) throw new Error('offline'); return 'ready' })
  await assert.rejects(retry(), /offline/)
  assert.equal(await retry(), 'ready')
})

test('known disabled service differs from an unexpected 503 without exposing internals', () => {
  assert.match(programAvailabilityMessage({ programs_available: false, reason: 'disabled' }), /비활성화/)
  assert.equal(programAvailabilityMessage({ programs_available: true }), '')
  assert.match(meetupErrorMessage({ status: 503, data: { detail: '신규 모임 API를 활성화하지 않았습니다. 배포 설정을 확인해주세요.' } }), /비활성화/)
  assert.match(meetupErrorMessage({ status: 503, data: { detail: 'private SQL details' } }), /연결/)
})
