import test from 'node:test'
import assert from 'node:assert/strict'
import { QueryCache } from '../src/queryCache.js'

test('fresh cache hits and in-flight requests are reused', async () => {
  const cache = new QueryCache()
  let calls = 0
  const fetcher = async () => { calls++; return { title: 'one' } }
  const [a, b] = await Promise.all([cache.read('posts', fetcher), cache.read('posts', fetcher)])
  assert.equal(calls, 1)
  assert.equal(a, b)
  assert.equal(await cache.read('posts', fetcher), a)
  assert.equal(calls, 1)
})
test('expired data is displayed while the next read refreshes it', async () => {
  const cache = new QueryCache()
  await cache.read('posts', async () => 'old')
  cache.entries.get('posts').time -= 31_000
  assert.equal(cache.peek('posts'), 'old')
  assert.equal(await cache.read('posts', async () => 'new'), 'new')
  cache.entries.get('posts').time -= 301_000
  assert.equal(cache.peek('posts'), undefined)
})
test('invalidation prevents old requests from repopulating the cache', async () => {
  const cache = new QueryCache()
  let resolveOld
  const old = cache.read('posts', () => new Promise(resolve => { resolveOld = resolve }))
  await Promise.resolve()
  cache.clear()
  await cache.read('posts', async () => 'new')
  resolveOld('old')
  await old
  assert.equal(cache.peek('posts'), 'new')
})
test('failed requests are retryable and cache size is bounded', async () => {
  const cache = new QueryCache({ maxEntries: 2 })
  await assert.rejects(cache.read('a', async () => { throw new Error('offline') }))
  assert.equal(await cache.read('a', async () => 'a'), 'a')
  await cache.read('b', async () => 'b')
  await cache.read('c', async () => 'c')
  assert.equal(cache.entries.size, 2)
  assert.equal(cache.peek('a'), undefined)
})
