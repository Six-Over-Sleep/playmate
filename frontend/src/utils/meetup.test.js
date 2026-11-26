import test from 'node:test'
import assert from 'node:assert/strict'
import { getMeetupStatus, toDateTimeLocal, normalizeMemberCount } from './meetup.js'
import { scheduleFromDeadline, validateMeetupForm, serverFieldErrors, meetupErrorMessage, pickPayload, programCreateFields, programEditFields, legacyCreateFields } from './meetupForm.js'
import { getChangedProgramFields } from './meetupForm.js'
const form = {
  title: '함께 공부', body: '소개', category: 'study', capacity: 3, is_online: true,
  recruit_mode: 'regular', regular_start_date: '2030-01-07', regular_time: '19:00',
  regular_days: ['월'], recruit_end: '2030-01-06T19:00', ends_at: '2030-02-07T19:00',
  study_topic: 'SQL', required_skill_ids: [], creator_skill_ids: [],
}
const now = Date.parse('2030-01-01T00:00:00+09:00')

test('title-only regular edit does not resend equivalent time or schedule', () => {
  const original = {
    title: '기존 제목', regular_time: '19:00:00', regular_days: ['월'],
    starts_at: '2030-01-07T10:00:00Z',
    required_skill_ids: [2, 1], permissions: { can_edit_configuration: true },
  }
  assert.deepEqual(getChangedProgramFields({
    title: '새 제목', regular_time: '19:00', regular_days: ['월'],
    starts_at: '2030-01-07T19:00:00+09:00', required_skill_ids: [1, 2],
  }, original), { title: '새 제목' })
  assert.deepEqual(getChangedProgramFields({ regular_time: '20:00' }, original), {
    regular_time: '20:00',
  })
  assert.deepEqual(getChangedProgramFields({ regular_time: '20:00' }, {
    ...original, permissions: { can_edit_configuration: false },
  }), {})
})
test('regular study accepts matching Seoul date, weekday and deadline', () => {
  assert.deepEqual(validateMeetupForm(form, { now }), {})
})
test('required fields, weekday and date ordering expose field-specific errors', () => {
  const errors = validateMeetupForm({ ...form, title: ' ', capacity: '', regular_days: [], ends_at: '2030-01-01T19:00' }, { now })
  for (const key of ['title','capacity','regular_days','ends_at']) assert.ok(errors[key])
})
test('project requires real selected and assigned skills', () => {
  const errors = validateMeetupForm({ ...form, category: 'project' }, { now })
  assert.ok(errors.required_skill_ids)
  assert.ok(errors.creator_skill_ids)
  assert.deepEqual(validateMeetupForm({ ...form, category: 'project', required_skill_ids: [11], creator_skill_ids: [11] }, { now }), {})
})
test('short schedules and group purchase use their own required fields', () => {
  assert.deepEqual(validateMeetupForm({ ...form, recruit_mode: 'short', meeting_start: '2030-01-07T19:00', meeting_end: '2030-01-07T21:00' }, { now }), {})
  const errors = validateMeetupForm({ ...form, category: 'group_buy' }, { now, program: false })
  assert.ok(errors.product_name)
  assert.ok(errors.estimated_price_per_person)
  assert.ok(errors.pickup_method)
})
test('program payload excludes legacy-only and unrelated fields', () => {
  const payload = pickPayload({ ...form, game_name: null, place_latitude: null, meeting_datetime: null }, programCreateFields)
  assert.equal('game_name' in payload, false)
  assert.equal('place_latitude' in payload, false)
  assert.equal('meeting_datetime' in payload, false)
  assert.deepEqual(
    pickPayload({ title: '수정', is_online: false, regular_days: ['월'] }, programEditFields),
    { title: '수정', regular_days: ['월'] },
  )
})
test('API validation locations map to form and internal failures stay private', () => {
  const errors = serverFieldErrors({ data: { detail: [{ loc: ['body','deadline_at'], type: 'missing', msg: 'Field required' }] } }, form)
  assert.ok(errors.recruit_end)
  assert.equal(meetupErrorMessage({ status: 500, message: 'secret stack trace' }).includes('secret'), false)
  assert.match(meetupErrorMessage({ status: 401 }), /로그인/)
})
test('UTC and offset edit values become Seoul wall time', () => {
  assert.equal(toDateTimeLocal('2030-01-07T10:00:00Z'), '2030-01-07T19:00')
  assert.equal(toDateTimeLocal('2030-01-07T19:00:00+09:00'), '2030-01-07T19:00')
  assert.equal(toDateTimeLocal('2030-01-07T19:00:00'), '2030-01-07T19:00')
})
test('game full and deadline are distinct; deadline wins over full', () => {
  assert.equal(getMeetupStatus({ category: 'game', state: 'OPEN', capacity: 2, participant_count: 2, deadline_at: '2099-01-01T00:00:00+09:00' }).className, 'full')
  assert.equal(getMeetupStatus({ category: 'game', state: 'OPEN', capacity: 2, participant_count: 2, deadline_at: '2020-01-01T00:00:00+09:00' }).className, 'deadline')
  assert.equal(getMeetupStatus({ category: 'game', state: 'OPEN', capacity: 2, participant_count: 1 }).className, 'open')
  assert.equal(normalizeMemberCount({ current_members: 0 }), 0)
})

test('legacy category requests never carry new-program discriminator fields', () => {
  const payload = pickPayload({ title: '게임', category: 'game', recruit_mode: 'short', study_type: null, difficulty: null, game_name: '체스' }, legacyCreateFields)
  assert.equal('study_type' in payload, false)
  assert.equal('difficulty' in payload, false)
  assert.equal(payload.game_name, '체스')
})

test('choosing a deadline adjusts short start by 24 hours in Seoul across year boundary', () => {
  const result = scheduleFromDeadline({ recruit_mode: 'short' }, '2030-12-31T23:30')
  assert.deepEqual(result, { recruit_end: '2030-12-31T23:30', meeting_start: '2031-01-01T23:30' })
})
test('regular deadline updates date, time and selected weekday without duplicates', () => {
  const result = scheduleFromDeadline(form, '2030-01-07T19:00')
  assert.equal(result.regular_start_date, '2030-01-08')
  assert.equal(result.regular_time, '19:00')
  assert.deepEqual(result.regular_days, ['월', '화'])
  assert.deepEqual(scheduleFromDeadline({ ...form, regular_days: ['월', '화'] }, '2030-01-07T19:00').regular_days, ['월', '화'])
  assert.deepEqual(scheduleFromDeadline(form, '2030-01-07T19:00', { preserveWeekdays: true }).regular_days, ['월'])
  assert.deepEqual(scheduleFromDeadline(form, ''), { recruit_end: '' })
})
