import test from 'node:test'
import assert from 'node:assert/strict'
import { createMeetupRequestGate } from './meetupRequest.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('overlapping loads for one member send a single request and refresh after completion', async () => {
  const gate = createMeetupRequestGate()
  const pending = deferred()
  let calls = 0
  const load = () => { calls++; return pending.promise }
  const first = gate.get(1, load)
  const second = gate.get(1, load)
  assert.equal(first, second)
  await Promise.resolve()
  assert.equal(calls, 1)
  pending.resolve([])
  await first.promise
  const refreshed = gate.get(1, load)
  assert.notEqual(first, refreshed)
  await refreshed.promise
  assert.equal(calls, 2)
})

test('mutation refresh and member changes invalidate older responses', async () => {
  const gate = createMeetupRequestGate()
  const pending = deferred()
  const old = gate.get(1, () => pending.promise)
  const fresh = gate.get(1, async () => ['new'], { force: true })
  assert.equal(old.isCurrent(), false)
  assert.deepEqual(await fresh.promise, ['new'])
  const another = gate.get(2, async () => ['member2'])
  assert.equal(fresh.isCurrent(), false)
  assert.deepEqual(await another.promise, ['member2'])
  pending.resolve(['old'])
  await old.promise
  assert.equal(another.isCurrent(), true)
})

test('failed requests can be retried without reusing a rejected promise', async () => {
  const gate = createMeetupRequestGate()
  const failed = gate.get(1, async () => { throw new Error('unavailable') })
  await assert.rejects(failed.promise)
  const retry = gate.get(1, async () => ['ok'])
  assert.notEqual(failed, retry)
  assert.deepEqual(await retry.promise, ['ok'])
})
