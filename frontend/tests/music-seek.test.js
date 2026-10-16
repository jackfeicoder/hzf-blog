import test from 'node:test'
import assert from 'node:assert/strict'
import { SeekGesture, seekPosition, bufferedRanges } from '../src/music/seekGesture.js'

test('pointer coordinates account for thumb inset and clamp outside the track', () => {
  const rect = { left: 100, width: 214 }
  assert.equal(seekPosition(107, rect, 60), 0)
  assert.equal(seekPosition(207, rect, 60), 30)
  assert.equal(seekPosition(307, rect, 60), 60)
  assert.equal(seekPosition(-100, rect, 60), 0)
  assert.equal(seekPosition(900, rect, 60), 60)
  assert.equal(seekPosition(308, rect, 59.97), 59.97)
  assert.equal(seekPosition(207, rect, Infinity), null)
  assert.equal(seekPosition(207, { left: 100, width: 0 }, 60), null)
})
test('release coordinate is authoritative even when the last move event is missing', () => {
  const gesture = new SeekGesture(), rect = { left: 0, width: 214 }
  gesture.begin('song-a', 10)
  gesture.update('song-a', seekPosition(107, rect, 60))
  gesture.update('song-a', seekPosition(157, rect, 60))
  assert.equal(gesture.finish('song-a'), 45)
  assert.equal(gesture.finish('song-a', false), null) // lost capture after release
})

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
