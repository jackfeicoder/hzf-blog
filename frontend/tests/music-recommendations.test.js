import test from 'node:test'
import assert from 'node:assert/strict'
import { RecommendationFeed, RECOMMENDATION_KEY } from '../src/music/recommendations.js'

const song = { source: 'wy', id: '1', name: '测试歌曲', singer: '测试歌手' }
const data = (songs = [song]) => ({ songs })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const memory = initial => { const values = new Map(initial ? [[RECOMMENDATION_KEY, JSON.stringify(initial)]] : []); return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) } }

test('recommendations show public browser cache before any network request', () => {
  let calls = 0
  const feed = new RecommendationFeed(() => { calls++ }, { storage: memory(data()) })
  assert.equal(feed.value.songs[0].name, song.name); assert.equal(calls, 0)
  assert.equal(feed.value.owner, 'administrator')
})

test('one shared request survives repeated visible/manual refresh triggers', async () => {
  let calls = 0; const pending = deferred()
  const feed = new RecommendationFeed(async () => { calls++; return pending.promise }, { storage: memory() })
  const first = feed.load(), second = feed.load(true)
  assert.equal(first, second); assert.equal(feed.shouldRefresh(), false)
  pending.resolve(data()); await first
  assert.equal(calls, 1); assert.equal(feed.shouldRefresh(), false)
})

test('transient failure retries in background, preserving prior content and cooling down', async () => {
  let calls = 0, now = 0; const waits = []
  const feed = new RecommendationFeed(async () => { calls++; throw new TypeError('offline') }, {
    storage: memory(data()), now: () => now, wait: async value => { waits.push(value) },
  })
  await assert.rejects(feed.load(), /offline/)
  assert.equal(calls, 2); assert.deepEqual(waits, [1500]); assert.equal(feed.value.songs.length, 1)
  await feed.load(); assert.equal(calls, 2)
  now = 15001; assert.equal(feed.shouldRefresh(), true)
})

test('a legitimate empty recommendation replaces old content and persists across remount', async () => {
  const storage = memory(data()), feed = new RecommendationFeed(async () => data([]), { storage })
  assert.deepEqual((await feed.load()).songs, [])
  assert.deepEqual(new RecommendationFeed(null, { storage }).value.songs, [])
})

test('bad responses and broken storage do not replace usable public recommendations', async () => {
  const feed = new RecommendationFeed(async () => ({ songs: [{ ...song, source: 'unknown' }] }), { storage: memory(data()) })
  await assert.rejects(feed.load()); assert.equal(feed.value.songs[0].source, 'wy')
  const broken = { getItem() { throw new Error('private mode') }, setItem() { throw new Error('quota') } }
  const second = new RecommendationFeed(async () => data(), { storage: broken })
  assert.equal((await second.load()).songs.length, 1)
  assert.equal(new RecommendationFeed(null, { storage: memory({ songs: 'bad' }) }).value, null)
})

test('unmount cancellation permits a fresh load and late data cannot overwrite it', async () => {
  const stale = deferred(); let calls = 0
  const feed = new RecommendationFeed(async () => ++calls === 1 ? stale.promise : data([{ ...song, id: '2' }]), { storage: memory() })
  const first = feed.load(); const cancelled = assert.rejects(first, error => error.name === 'AbortError')
  await Promise.resolve(); feed.cancel()
  await feed.load(); stale.resolve(data()); await cancelled
  assert.equal(feed.value.songs[0].id, '2'); assert.equal(calls, 2)
})

test('rate limit and authorization failures are not immediately retried', async () => {
  for (const status of [401, 403, 429]) {
    let calls = 0
    const feed = new RecommendationFeed(async () => { calls++; throw Object.assign(new Error('denied'), { status }) }, { storage: memory() })
    await assert.rejects(feed.load()); assert.equal(calls, 1)
  }
})
