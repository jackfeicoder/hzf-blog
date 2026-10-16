import test from 'node:test'
import assert from 'node:assert/strict'
import { SeekGesture, bufferedRanges } from '../src/music/seekGesture.js'

test('drag previews many positions and commits exactly once', () => {
  const gesture = new SeekGesture()
  gesture.begin('song-a', 10)
  for (let i = 11; i < 50; i++) gesture.update('song-a', i)
  assert.equal(gesture.finish('song-a'), 49)
  assert.equal(gesture.finish('song-a'), null)
})
test('cancel or a song change discards the old seek', () => {
  const gesture = new SeekGesture()
  gesture.begin('song-a', 10); gesture.update('song-a', 20)
  assert.equal(gesture.finish('song-b'), null)
  gesture.begin('song-b', 30)
  assert.equal(gesture.finish('song-b', false), null)
})
test('buffered ranges preserve holes and clamp to duration', () => {
  assert.deepEqual(bufferedRanges({ duration: 100, buffered: { length: 2, start: i => [0, 60][i], end: i => [30, 120][i] } }), [[0, 30], [60, 100]])
  assert.deepEqual(bufferedRanges({ duration: Infinity }), [])
})
