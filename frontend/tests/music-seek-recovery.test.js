import test, { beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { MusicController } from '../src/music/controller.js'
import { PlaybackAddresses } from '../src/music/playbackAddresses.js'
import { music } from '../src/music/store.js'

const url = '/api/music/stream/' + 'a'.repeat(64)
const nextURL = '/api/music/stream/' + 'b'.repeat(64)
const song = { source: 'wy', id: 'test', name: 'Synthetic audio', duration: 240 }
const file = { url, quality: '128k', file_cache_hit: true, source_id: 0, source_name: '本机缓存' }
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
class AudioMock {
  constructor() { this.handlers = {}; this.duration = 240; this.currentTime = 0; this.paused = true; this.readyState = 4; this.attributes = {}; this.played = 0 }
  addEventListener(name, fn) { this.handlers[name] = fn }
  removeEventListener(name) { delete this.handlers[name] }
  set src(value) { this.attributes.src = value }
  getAttribute(name) { return this.attributes[name] }
  removeAttribute(name) { delete this.attributes[name] }
  pause() { this.paused = true; this.handlers.pause?.() }
  load() {}
  async play() { this.paused = false; this.played++ }
}
beforeEach(() => { music.set({ current: null, queue: [], actor: null, library: music.guestLists(), libraryLoading: false, status: 'idle', quality: '128k' }); music.progress({ time: 0, duration: 0, buffered: [] }) })
function setup(request = async () => ({})) {
  const addresses = new PlaybackAddresses({ getItem: () => null, setItem() {} })
  addresses.put(song, '128k', file)
  const audio = new AudioMock(), controller = new MusicController(audio, request, undefined, addresses)
  return { audio, controller, addresses }
}

test('drag release and seeked always restore monitoring, including readyState 4 and a later stalled-only event', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100000 })
  const { audio, controller } = setup(), recoveries = []
  t.after(() => controller.destroy())
  await controller.play(song); music.set({ status: 'playing' })
  controller.previewSeek(true); controller.seek(100); controller.previewSeek(false)
  assert.ok(controller.timer)
  audio.handlers.seeked(); assert.ok(controller.timer)
  audio.readyState = 2; audio.handlers.stalled()
  assert.equal(music.get().status, 'buffering')
  controller.fallback = reason => recoveries.push(reason)
  for (let i = 0; i < 4; i++) t.mock.timers.tick(5000)
  assert.deepEqual(recoveries, ['stalled'])
})

test('first cached retry starts immediately with a fresh connection key and never calls the resolver', async t => {
  const paths = [], { audio, controller, addresses } = setup(async path => { paths.push(path); return {} })
  t.after(() => controller.destroy())
  await controller.play(song); audio.currentTime = 90
  const played = audio.played, result = controller.fallback('stalled')
  assert.equal(audio.played, played + 1); assert.equal(audio.currentTime, 90)
  assert.ok(audio.getAttribute('src').startsWith(url + '?connection='))
  assert.ok(!paths.includes('/resolve') && !paths.includes('/cached'))
  await result; assert.equal(controller.switching, false)
  audio.handlers.playing()
  const successful = audio.getAttribute('src')
  assert.equal(addresses.get(song, '128k').url, successful)
  await controller.play(song); assert.equal(audio.getAttribute('src'), successful)
})

test('an unresolved play promise does not lock direct cache reconnection', async t => {
  const { audio, controller } = setup(), pending = deferred()
  t.after(() => { controller.destroy(); pending.resolve() })
  audio.play = () => pending.promise
  await controller.play(song); await controller.fallback('error')
  assert.equal(controller.switching, false); assert.ok(controller.url.includes('?connection='))
})

test('cache-index timeout is bounded to 4s and never falls into two 32s resolver waits; explicit seek retries', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 100000 })
  const paths = [], { audio, controller } = setup((path, options) => {
    paths.push(path)
    if (path !== '/cached') return Promise.resolve({})
    assert.equal(options.timeout, 4000)
    return new Promise((_, reject) => setTimeout(() => reject(new Error('transport')), options.timeout))
  })
  t.after(() => controller.destroy())
  await controller.play(song); await controller.fallback('error')
  const second = controller.fallback('error')
  t.mock.timers.tick(4000); await second
  assert.equal(Date.now(), 104000); assert.equal(controller.desired, false)
  assert.equal(music.get().status, 'error'); assert.ok(!paths.includes('/resolve'))
  controller.seek(45)
  assert.equal(controller.desired, true); assert.equal(audio.currentTime, 45)
  assert.ok(controller.url.includes('?connection='))
})

test('a completed cache-only miss permits upstream resolve, but no earlier retry does', async t => {
  const paths = [], { controller } = setup(async path => {
    paths.push(path)
    return path === '/cached' ? null : path === '/resolve' ? { url: '/upstream', source_id: 1 } : {}
  })
  t.after(() => controller.destroy())
  await controller.play(song); await controller.fallback('error')
  assert.ok(!paths.includes('/resolve'))
  await controller.fallback('error')
  assert.deepEqual(paths.filter(p => ['/cached', '/resolve'].includes(p)), ['/cached', '/resolve'])
  assert.equal(controller.url, '/upstream')
})

test('malformed cache lookup data is not a cache miss and cannot start slow source resolution', async t => {
  const paths = [], { controller } = setup(async path => { paths.push(path); return {} })
  t.after(() => controller.destroy())
  await controller.play(song); await controller.fallback('error'); await controller.fallback('error')
  assert.equal(controller.desired, false); assert.equal(music.get().status, 'error')
  assert.ok(!paths.includes('/resolve'))
})

test('latest seek wins over a pending cache lookup, including backwards seeking to zero', async t => {
  const wait = deferred(), { audio, controller } = setup(path => path === '/cached' ? wait.promise : Promise.resolve({}))
  t.after(() => controller.destroy())
  await controller.play(song); audio.currentTime = 10; await controller.fallback('error')
  const second = controller.fallback('error')
  controller.seek(150); controller.seek(0)
  wait.resolve({ ...file, url: nextURL }); await second
  assert.equal(audio.currentTime, 0); assert.equal(controller.recoveryStart, 0)
  assert.ok(controller.url.startsWith(nextURL + '?connection='))
})

test('latest seek also wins over an in-flight non-file resolver', async t => {
  const wait = deferred(), { audio, controller, addresses } = setup(path => path === '/resolve' ? wait.promise : Promise.resolve({}))
  t.after(() => controller.destroy())
  addresses.forget(song, '128k')
  const first = controller.play(song)
  controller.seek(150)
  wait.resolve({ url: '/upstream', source_id: 1 }); await first
  assert.equal(audio.currentTime, 150)
})

test('metadata arrival applies the newest target, not an old reconnect target; a pause remains paused', async t => {
  const { audio, controller } = setup()
  t.after(() => controller.destroy())
  await controller.play(song); audio.currentTime = 10
  audio.load = () => { audio.readyState = 0; audio.duration = NaN }
  await controller.fallback('error')
  controller.seek(80); controller.seek(0); controller.toggle()
  const played = audio.played
  audio.readyState = 4; audio.duration = 240; audio.handlers.loadedmetadata()
  assert.equal(audio.played, played); assert.equal(controller.desired, false)
  controller.toggle()
  assert.equal(audio.currentTime, 0); assert.equal(controller.seekAfterLoad, null)
})

test('pause during pending cache lookup prevents autoplay after its result arrives', async t => {
  const wait = deferred(), { audio, controller } = setup(path => path === '/cached' ? wait.promise : Promise.resolve({}))
  t.after(() => controller.destroy())
  await controller.play(song); await controller.fallback('error')
  const pending = controller.fallback('error'); controller.toggle()
  const played = audio.played
  wait.resolve(file); await pending
  assert.equal(controller.desired, false); assert.equal(audio.played, played); assert.equal(music.get().status, 'paused')
})

test('switching songs cancels the relevance of a late old cache lookup', async t => {
  const wait = deferred(), { audio, controller, addresses } = setup(path => path === '/cached' ? wait.promise : Promise.resolve({}))
  t.after(() => controller.destroy())
  await controller.play(song); await controller.fallback('error')
  const old = controller.fallback('error'), other = { ...song, id: 'other' }
  addresses.put(other, '128k', { ...file, url: nextURL })
  await controller.play(other); wait.resolve(file); await old
  assert.equal(music.get().current.id, 'other'); assert.equal(audio.getAttribute('src'), nextURL)
})

test('a cache lookup timeout after manual pause cannot replace paused state with an error', async t => {
  const pending = deferred(), { controller } = setup(path => path === '/cached' ? pending.promise.then(() => { throw new Error('timeout') }) : Promise.resolve({}))
  t.after(() => controller.destroy())
  await controller.play(song); await controller.fallback('error')
  const old = controller.fallback('error'); controller.toggle(); pending.resolve(); await old
  assert.equal(controller.desired, false); assert.equal(music.get().status, 'paused')
})

test('cached reconnection remains bounded, never skips or deletes, and manual retry still works', async t => {
  const paths = [], { controller } = setup(async path => { paths.push(path); return path === '/cached' ? file : {} })
  t.after(() => controller.destroy())
  await controller.play(song, [song, { ...song, id: 'next' }])
  await controller.fallback('error'); await controller.fallback('error'); await controller.fallback('error')
  assert.equal(controller.desired, false); assert.equal(music.get().current.id, song.id)
  assert.equal(controller.failedSongs.size, 0); assert.ok(!paths.includes('/resolve'))
  await controller.retry(); assert.equal(controller.desired, true)
  assert.ok(controller.url.includes('?connection='))
})

test('the native pause at natural end does not cancel next-song playback, but stale ended is ignored', async t => {
  const { audio, controller } = setup(), advanced = []
  t.after(() => controller.destroy())
  await controller.play(song)
  controller.next = (...args) => advanced.push(args)
  audio.paused = true; audio.ended = true; audio.handlers.pause()
  assert.equal(controller.desired, true)
  audio.handlers.ended(); assert.deepEqual(advanced, [[1, true]])
  audio.ended = false; audio.handlers.ended(); assert.equal(advanced.length, 1)
})
