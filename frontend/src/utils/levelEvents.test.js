import test from 'node:test'
import assert from 'node:assert/strict'
import { notifyMyLevelUpdated, onMyLevelUpdated } from './levelEvents.js'

test('attendance level update reaches the header preview until it unsubscribes', () => {
  const target = new EventTarget()
  const seen = []
  const unsubscribe = onMyLevelUpdated((level) => seen.push(level.total_xp), target)

  notifyMyLevelUpdated({ level: 1, total_xp: 1 }, target)
  unsubscribe()
  notifyMyLevelUpdated({ level: 1, total_xp: 2 }, target)

  assert.deepEqual(seen, [1])
})
