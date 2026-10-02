import test from 'node:test'
import assert from 'node:assert/strict'
import { MusicController } from '../src/music/controller.js'
import { music } from '../src/music/store.js'
import { MusicApiError } from '../src/music/api.js'
class AudioMock {
  constructor() { this.handlers = {}; this.duration = 60; this.currentTime = 0; this.attributes = {}; this.played = 0 }
  addEventListener(k, fn) { this.handlers[k] = fn }
  removeEventListener(k) { delete this.handlers[k] }
  set src(v) { this.attributes.src = v }
  getAttribute(k) { return this.attributes[k] }
  removeAttribute(k) { delete this.attributes[k] }
  pause() { this.handlers.pause?.() }
  load() {}
  async play() { this.played++; this.handlers.playing?.() }
}
const song = id => ({ source: 'wy', id: String(id), name: String(id) })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
test('playback settings select valid modes without resolving or restarting audio', () => {
  const a = new AudioMock(), c = new MusicController(a, () => { throw new Error('unexpected network call') })
  c.mode('shuffle'); assert.equal(music.get().mode, 'shuffle')
  c.mode('single'); assert.equal(music.get().mode, 'single')
  c.mode('invalid'); assert.equal(music.get().mode, 'single')
  c.mode(); assert.equal(music.get().mode, 'sequence')
  c.volume(.35); assert.equal(music.get().volume, .35); assert.equal(a.volume, .35)
  assert.equal(a.played, 0); c.destroy()
})
test('late resolver cannot replace newly selected song; pause during loading is respected', async () => {
  const a = new AudioMock(), waits = []
  const c = new MusicController(a, async path => {
    if (path.startsWith('/lyrics')) return {}
    const d = deferred(); waits.push(d); return d.promise
  })
  const first = c.play(song(1)), second = c.play(song(2))
  c.toggle() // Pause while second resolves.
  waits[1].resolve({ url: '/song2', source_id: 2, source_name: 'second' }); await second
  waits[0].resolve({ url: '/song1', source_id: 1, source_name: 'first' }); await first
  assert.equal(a.getAttribute('src'), '/song2'); assert.equal(music.get().current.id, '2'); assert.equal(a.played, 0)
  c.toggle(); await Promise.resolve(); assert.equal(a.played, 1); c.destroy()
})
test('logout cancels pending personal library and stale callbacks cannot restore it', async () => {
  const wait = deferred(), a = new AudioMock(), c = new MusicController(a, () => wait.promise)
  const first = c.actor({ id: 1, username: 'alice' }); await c.actor(null)
  wait.resolve([{ id: 100, kind: 'favorites', name: 'Private', songs: [song(1)] }]); await first
  assert.equal(music.get().actor, null); assert.equal(music.get().library[0].songs.length, 0); c.destroy()
})
test('autoplay denial pauses rather than changing source', async () => {
  const a = new AudioMock(); a.play = async () => { const e = new Error(); e.name = 'NotAllowedError'; throw e }
  let resolves = 0
  const c = new MusicController(a, async path => path.startsWith('/lyrics') ? {} : (resolves++, { url: '/audio', source_id: 1, source_name: 'one' }))
  await c.play(song(1)); assert.equal(music.get().status, 'paused'); assert.equal(resolves, 1); assert.equal(c.failures.length, 1); c.destroy()
})

test('playback retries a gateway failure once and then plays', async () => {
  const a = new AudioMock(); let calls = 0
  const c = new MusicController(a, async path => {
    if (path.startsWith('/lyrics')) return {}
    if (++calls === 1) throw new MusicApiError('gateway', 502, true)
    return { url: '/audio', source_id: 1, source_name: 'one' }
  })
  await c.play(song(1)); assert.equal(calls, 2); assert.equal(a.played, 1); c.destroy()
})

test('persistent gateway failures stop at two, JSON exhausted sources are not retried', async () => {
  for (const gateway of [true, false]) {
    let calls = 0; const c = new MusicController(new AudioMock(), async path => {
      if (path.startsWith('/lyrics')) return {}
      calls++; throw new MusicApiError('failed', 502, gateway)
    })
    await c.play(song(1)); assert.equal(calls, gateway ? 2 : 1); assert.equal(music.get().status, 'error'); c.destroy()
  }
})

test('pause during gateway failure prevents automatic retry', async () => {
  let calls = 0; const c = new MusicController(new AudioMock(), async path => {
    if (path.startsWith('/lyrics')) return {}
    calls++; c.toggle(); throw new MusicApiError('failed', 502, true)
  })
  await c.play(song(1)); assert.equal(calls, 1); assert.equal(c.desired, false); c.destroy()
})
