import test from 'node:test'
import assert from 'node:assert/strict'
import { createPlayerDock } from '../src/music/playerDock.js'

test('desktop uses the same dock node; mobile and unmounted routes use the global player', () => {
  let desktop = true
  const dock = createPlayerDock(() => desktop), target = { id: 'music-player-dock' }
  assert.equal(dock.get(), null)
  dock.set(target)
  assert.equal(dock.get(), target)
  assert.equal(dock.get(), target) // Stable React snapshot, no render loop.
  desktop = false
  assert.equal(dock.get(), null)
  desktop = true
  assert.equal(dock.get(), target)
  dock.set(null)
  assert.equal(dock.get(), null)
})

test('mount/unmount and breakpoint changes notify; repeat refs and unsubscribed views do not', () => {
  const dock = createPlayerDock(() => true), target = {}, events = []
  const unsubscribe = dock.subscribe(() => events.push(dock.get()))
  dock.set(target); dock.set(target); dock.notify(); dock.set(null)
  assert.deepEqual(events, [target, target, null])
  unsubscribe(); dock.set(target)
  assert.equal(events.length, 3)
})
