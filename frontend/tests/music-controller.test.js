import test, { beforeEach } from 'node:test'
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
beforeEach(() => { music.set({ queue: [], current: null, mode: 'sequence', actor: null, library: music.guestLists(), libraryLoading: false, message: '' }); music.progress({ time: 0, duration: 0 }) })

test('seek preview suspends watchdog without seeking; commit updates once and resets stable-progress baseline', () => {
  const a = new AudioMock(), c = new MusicController(a, () => { throw new Error('unexpected resolve') })
  c.desired = true; c.url = '/audio'
  c.watchdog(); assert.ok(c.timer)
  c.previewSeek(true); c.watchdog(); assert.equal(c.timer, null); assert.equal(a.currentTime, 0)
  c.previewSeek(false); c.seek(40)
  assert.equal(a.currentTime, 40); assert.equal(c.recoveryStart, 40); assert.ok(c.timer)
  c.seek(NaN); assert.equal(a.currentTime, 40)
  c.destroy()
})
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
  await c.play(song(1)); assert.equal(music.get().status, 'paused'); assert.equal(resolves, 1); assert.equal(c.failures.length, 0); c.destroy()
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

test('interrupted playback refreshes same route once then excludes it, preserving progress and lyrics', async () => {
  const a = new AudioMock(), requests = []
  const url = '/api/music/stream/' + 'a'.repeat(32)
  const route = '1:wy:1:128k'
  const c = new MusicController(a, async (path, options) => {
    if (path.startsWith('/lyrics')) return { lyric: '[00:01]歌词', translation: '' }
    if (path === '/feedback') return null
    requests.push(options.body)
    return { url, source_id: 1, source_name: 'one', attempted: [route], playback_song: song(1), quality: '128k' }
  })
  await c.play(song(1)); await Promise.resolve()
  a.currentTime = 27
  await c.fallback()
  assert.equal(requests[1].refresh_token, 'a'.repeat(32))
  assert.deepEqual(requests[1].attempted, [])
  assert.equal(a.currentTime, 27)
  assert.equal(music.get().lyrics[0].text, '歌词')
  // The refreshed URL can fail before metadata loads, resetting currentTime.
  a.currentTime = 0; c.seekAfterLoad = 27; c.lastPosition = 0
  await c.fallback()
  assert.equal(requests[2].refresh_token, '')
  assert.deepEqual(requests[2].attempted, [route])
  assert.equal(a.currentTime, 27)
  c.destroy()
})

test('continuation carries failed routes forward and is bounded to three batches', async () => {
  const a = new AudioMock(), bodies = []
  const c = new MusicController(a, async (path, options) => {
    if (path.startsWith('/lyrics')) return {}
    bodies.push(options.body)
    const e = new MusicApiError('more candidates', 502)
    e.continuation = true; e.attempted = [`${bodies.length}:wy:1:128k`]; throw e
  })
  await c.play(song(1))
  assert.equal(bodies.length, 3)
  assert.deepEqual(bodies[1].attempted, ['1:wy:1:128k'])
  assert.equal(music.get().status, 'error')
  c.destroy()
})

test('lyrics can finish independently of fallback and never leak into a newly selected song', async () => {
  const a = new AudioMock(), waits = []
  const c = new MusicController(a, async path => {
    if (path.startsWith('/lyrics')) { const wait = deferred(); waits.push(wait); return wait.promise }
    return { url: '/audio', source_id: 1, source_name: 'one' }
  })
  await c.play(song(1)); await c.play(song(2))
  waits[1].resolve({ lyric: '[00:01]第二首', translation: '' }); await Promise.resolve(); await Promise.resolve()
  waits[0].resolve({ lyric: '[00:01]第一首', translation: '' }); await Promise.resolve(); await Promise.resolve()
  assert.equal(music.get().lyrics[0].text, '第二首')
  assert.equal(music.get().current.id, '2')
  c.destroy()
})

test('immediate failure of a refreshed URL is not dropped behind the switching lock', async () => {
  const a = new AudioMock(); let calls = 0
  const c = new MusicController(a, async path => {
    if (path.startsWith('/lyrics')) return {}
    calls++
    const source_id = calls >= 3 ? 2 : 1
    return { url: `/audio${calls}`, source_id, source_name: String(source_id), attempted: [`${source_id}:wy:1:128k`] }
  })
  a.play = async () => {
    if (calls === 2) { a.handlers.error(); throw new DOMException('unsupported', 'NotSupportedError') }
    a.handlers.playing()
  }
  await c.play(song(1)); await c.fallback()
  for (let i = 0; i < 12; i++) await Promise.resolve()
  assert.equal(calls, 3)
  assert.equal(a.getAttribute('src'), '/audio3')
  assert.equal(music.get().status, 'playing')
  c.destroy()
})

test('exhausted sources skip successive failed songs and play the next available song', async () => {
  const a = new AudioMock(), ids = []
  const c = new MusicController(a, async (path, options) => {
    if (path.startsWith('/lyrics')) return {}
    ids.push(options.body.song.id)
    if (options.body.song.id !== '3') throw new MusicApiError('all sources failed', 502)
    return { url: '/song3', source_id: 1, source_name: 'one' }
  })
  await c.play(song(1), [song(1), song(2), song(3)])
  assert.deepEqual(ids, ['1', '2', '3'])
  assert.equal(music.get().current.id, '3'); assert.equal(a.played, 1)
  assert.equal(music.get().status, 'playing'); c.destroy()
})

test('an entirely unavailable queue stops after one round even in repeat-one or shuffle', async () => {
  for (const mode of ['sequence', 'single', 'shuffle']) {
    const ids = [], c = new MusicController(new AudioMock(), async (path, options) => {
      if (path.startsWith('/lyrics')) return {}
      ids.push(options.body.song.id); throw new MusicApiError('all sources failed', 502)
    })
    c.mode(mode)
    await c.play(song(1), [song(1), song(2), song(3)])
    assert.equal(ids.length, 3); assert.equal(new Set(ids).size, 3)
    assert.equal(c.desired, false); assert.equal(music.get().status, 'error')
    assert.match(music.get().message, /本轮/); c.destroy()
  }
})

test('browser playback failures at the retry limit also advance to another song', async () => {
  const a = new AudioMock(), c = new MusicController(a, async (path, options) => {
    if (path.startsWith('/lyrics')) return {}
    return { url: '/song' + options.body.song.id, source_id: 1, source_name: 'one' }
  })
  await c.play(song(1), [song(1), song(2)])
  c.attempts = 13
  await c.fallback('stalled')
  assert.equal(music.get().current.id, '2'); assert.equal(music.get().status, 'playing')
  assert.equal(a.getAttribute('src'), '/song2'); c.destroy()
})

test('manual pause and late failures never start another song', async () => {
  let reject, calls = 0
  const wait = new Promise((resolve, fail) => { reject = fail })
  const c = new MusicController(new AudioMock(), async path => {
    if (path.startsWith('/lyrics')) return {}
    calls++; return wait
  })
  const loading = c.play(song(1), [song(1), song(2)])
  c.toggle(); reject(new MusicApiError('all failed', 502)); await loading
  assert.equal(calls, 1); assert.equal(music.get().current.id, '1'); assert.equal(c.desired, false)
  c.destroy()
})

test('account and rate-limit errors stop without burning through the queue', async () => {
  for (const status of [401, 403, 429]) {
    let calls = 0
    const c = new MusicController(new AudioMock(), async path => {
      if (path.startsWith('/lyrics')) return {}
      calls++; throw new MusicApiError('permission or rate limit', status)
    })
    await c.play(song(1), [song(1), song(2)])
    assert.equal(calls, 1); assert.equal(music.get().current.id, '1'); c.destroy()
  }
})

test('manual retry starts a fresh round; stable playback clears failure round', async () => {
  let unavailable = true
  const a = new AudioMock(), c = new MusicController(a, async path => {
    if (path.startsWith('/lyrics')) return {}
    if (unavailable) throw new MusicApiError('all sources failed', 502)
    return { url: '/audio', source_id: 1, source_name: 'one' }
  })
  await c.play(song(1), [song(1), song(2)])
  unavailable = false; await c.play(song(1))
  assert.equal(music.get().status, 'playing')
  c.failedSongs.add('wy:2'); a.currentTime = 3.1; a.paused = false; a.handlers.timeupdate()
  assert.equal(c.failedSongs.size, 0); c.destroy()
})

test('temporary source cooling does not burn through the whole song queue', async () => {
  let calls = 0
  const c = new MusicController(new AudioMock(), async path => {
    if (path.startsWith('/lyrics')) return {}
    calls++; const e = new MusicApiError('音源冷却中', 503); e.cooldown = true; throw e
  })
  await c.play(song(1), [song(1), song(2), song(3)])
  assert.equal(calls, 1); assert.equal(music.get().current.id, '1'); assert.equal(c.desired, false)
  c.destroy()
})
