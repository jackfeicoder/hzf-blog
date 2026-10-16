import test from 'node:test'
import assert from 'node:assert/strict'
import { nextUnfailedIndex } from '../src/music/logic.js'

const queue = [1, 2, 3, 4].map(id => ({ source: 'wy', id: String(id) }))
test('failure recovery wraps in order, skips failed songs, and ignores repeat-one', () => {
  assert.equal(nextUnfailedIndex(queue, queue[0], new Set(['wy:1', 'wy:2']), 'single'), 2)
  assert.equal(nextUnfailedIndex(queue, queue[3], new Set(['wy:4'])), 0)
  assert.equal(nextUnfailedIndex(queue, null, new Set()), 0)
  assert.equal(nextUnfailedIndex([], null, new Set()), -1)
})
test('shuffle only chooses unfailed songs; an exhausted queue has no candidate', () => {
  const failed = new Set(['wy:1', 'wy:3'])
  assert.equal(nextUnfailedIndex(queue, queue[0], failed, 'shuffle', () => 0), 1)
  assert.equal(nextUnfailedIndex(queue, queue[0], failed, 'shuffle', () => .99), 3)
  assert.equal(nextUnfailedIndex(queue, queue[0], new Set(queue.map(s => 'wy:' + s.id))), -1)
})
