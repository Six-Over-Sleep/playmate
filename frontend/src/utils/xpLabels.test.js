import test from 'node:test'
import assert from 'node:assert/strict'
import { xpActivityLabel } from './xpLabels.js'

test('attendance and policy-driven streak rows get readable labels', () => {
  assert.equal(xpActivityLabel('ATTEND'), '일일 출석')
  assert.equal(xpActivityLabel('STREAK_7'), '7일 연속 출석 보너스')
  assert.equal(xpActivityLabel('STREAK_3'), '3일 연속 출석 보너스')
  assert.equal(xpActivityLabel('STREAK_100'), '100일 연속 출석 보너스')
  assert.equal(xpActivityLabel('UNKNOWN_TYPE'), 'UNKNOWN_TYPE')
  assert.equal(xpActivityLabel(null), '기타 활동')
})
