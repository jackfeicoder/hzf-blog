import test from 'node:test'
import assert from 'node:assert/strict'
import { createMusicSearch } from '../src/music/search.js'
import { MusicApiError } from '../src/music/api.js'

const platform = path => new URLSearchParams(path.split('?')[1]).get('source')
const result = source => ({ items: [{ source, id: `${source}-id`, name: '枫' }], page: 1, has_more: false })
const fail = () => new MusicApiError('上游暂不可用', 502)

test('healthy preferred platform needs one request and preserves IDs', async () => {
  const calls = [], search = createMusicSearch(async (path, options) => {
    calls.push(platform(path)); assert.equal(options.timeout, 8000); return result(platform(path))
  })
  assert.deepEqual(await search({ query: '枫', source: 'tx' }), { ...result('tx'), source: 'tx', switched: false })
  assert.deepEqual(calls, ['tx'])
})

test('502 automatically races two backups, preserves actual platform, aborts loser', async () => {
  const calls = [], signals = [], search = createMusicSearch(async (path, options) => {
    const p = platform(path); calls.push(p); signals.push(options.signal)
    if (p === 'tx') throw fail()
    if (p === 'wy') return result(p)
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')), { once: true }))
  })
  const data = await search({ query: '枫', source: 'tx' })
  assert.equal(data.source, 'wy'); assert.equal(data.items[0].id, 'wy-id'); assert.equal(data.switched, true)
  assert.deepEqual(calls, ['tx', 'wy', 'kg']); assert.ok(signals.every(s => s.aborted))
})

test('network errors, timeouts and HTML gateways can fall back', async () => {
  for (const error of [Object.assign(new TypeError('network'), { retryable: true }), Object.assign(new DOMException('timeout', 'AbortError'), { retryable: true }), new MusicApiError('gateway', 502, true)]) {
    const search = createMusicSearch(async path => { if (platform(path) === 'tx') throw error; return result(platform(path)) })
    assert.equal((await search({ query: '枫', source: 'tx' })).switched, true)
  }
})

test('cooldown avoids a broken platform for 60 seconds, then probes it again', async () => {
  let now = 1000; const calls = [], search = createMusicSearch(async path => {
    const p = platform(path); calls.push(p); if (p === 'tx') throw fail(); return result(p)
  }, () => now)
  await search({ query: '枫', source: 'tx' }); calls.length = 0
  await search({ query: '晴天', source: 'tx' }); assert.ok(!calls.includes('tx'))
  now += 60001; calls.length = 0
  await search({ query: '晴天', source: 'tx' }); assert.equal(calls[0], 'tx')
})

test('all failures stop after three requests instead of looping', async () => {
  let calls = 0; const search = createMusicSearch(async () => { calls++; throw fail() })
  await assert.rejects(search({ query: '枫', source: 'tx' }), /已自动尝试备用平台/)
  assert.equal(calls, 3)
})

test('401, 403, 429 and validation errors never trigger platform retries', async () => {
  for (const status of [401, 403, 429, 422]) {
    let calls = 0; const search = createMusicSearch(async () => { calls++; throw new MusicApiError('stop', status) })
    await assert.rejects(search({ query: '枫', source: 'tx' }), e => e.status === status)
    assert.equal(calls, 1)
  }
})

test('page 2 failure never combines unrelated platform pages', async () => {
  let calls = 0; const search = createMusicSearch(async () => { calls++; throw fail() })
  await assert.rejects(search({ query: '枫', source: 'tx', page: 2 }), e => e.status === 502)
  assert.equal(calls, 1)
})

test('empty preferred results are valid; empty backup cannot beat useful results', async () => {
  let calls = 0; const empty = { items: [], page: 1, has_more: false }
  const direct = createMusicSearch(async () => { calls++; return empty })
  assert.equal((await direct({ query: '未知', source: 'tx' })).items.length, 0); assert.equal(calls, 1)
  const fallback = createMusicSearch(async path => { const p = platform(path); if (p === 'tx') throw fail(); return p === 'wy' ? empty : result(p) })
  assert.equal((await fallback({ query: '枫', source: 'tx' })).source, 'kg')
})

test('cancelled query returns abort and launches no later backups', async () => {
  const controller = new AbortController(); let calls = 0
  const search = createMusicSearch(async () => { calls++; controller.abort(); throw fail() })
  await assert.rejects(search({ query: '枫', source: 'tx', signal: controller.signal }), e => e.name === 'AbortError')
  assert.equal(calls, 1)
  await assert.rejects(search({ query: '枫', source: 'tx', signal: controller.signal }), e => e.name === 'AbortError')
  assert.equal(calls, 1)
})

test('cancelling while backups load aborts both, and does not blacklist them', async () => {
  const controller = new AbortController(); const calls = []
  const search = createMusicSearch(async (path, options) => {
    const p = platform(path); calls.push(p)
    if (p === 'tx') throw fail()
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')), { once: true }))
  })
  const pending = search({ query: '枫', source: 'tx', signal: controller.signal })
  await new Promise(resolve => setImmediate(resolve)); controller.abort()
  await assert.rejects(pending, e => e.name === 'AbortError')
  assert.deepEqual(calls, ['tx', 'wy', 'kg'])
})

test('mismatched provider IDs are rejected rather than mislabeled for playback', async () => {
  const search = createMusicSearch(async path => platform(path) === 'tx' ? result('wy') : result(platform(path)))
  const data = await search({ query: '枫', source: 'tx' })
  assert.notEqual(data.source, 'tx'); assert.equal(data.items[0].source, data.source)
})
