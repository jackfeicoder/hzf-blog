import test from 'node:test'
import assert from 'node:assert/strict'
import { addToQueue, formatTime, lyricIndex, nextIndex, parseLyrics } from '../src/music/logic.js'
const songs = [1, 2, 3].map(id => ({ source: 'wy', id: String(id), name: String(id) }))
test('LRC handles fractions, duplicate timestamp lines, offsets and binary lookup', () => {
  const lines = parseLyrics('[offset:100]\n[00:02.50][00:04.500]Hello\n[00:01.5]Start\n[ar:Artist]')
  assert.deepEqual(lines.map(l => l.time), [1.6, 2.6, 4.6])
  assert.equal(lyricIndex(lines, 0), -1); assert.equal(lyricIndex(lines, 2.6), 1); assert.equal(lyricIndex(lines, 100), 2)
  assert.deepEqual(parseLyrics('not timed'), []); assert.equal(formatTime(124.9), '2:04')
})
test('queue is deduplicated and insert-next preserves active song', () => {
  assert.deepEqual(addToQueue(songs, songs[2], songs[0], true).map(s => s.id), ['1', '3', '2'])
  assert.equal(addToQueue(songs, songs[0], songs[1]).length, 3)
})
test('sequence loops, manual next works in repeat-one, shuffle avoids current', () => {
  assert.equal(nextIndex(songs, songs[2], 'sequence'), 0)
  assert.equal(nextIndex(songs, songs[1], 'single', 1, true), 1)
  assert.equal(nextIndex(songs, songs[1], 'single'), 2)
  assert.equal(nextIndex(songs, songs[1], 'shuffle', 1, true, () => 0), 0)
  assert.equal(nextIndex([], null, 'sequence'), -1)
})
