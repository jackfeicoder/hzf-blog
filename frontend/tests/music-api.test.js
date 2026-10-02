import test from 'node:test'
import assert from 'node:assert/strict'
import { musicApi } from '../src/music/api.js'

test('music API handles HTML gateway errors without exposing JSON/HTML internals', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<!DOCTYPE html><h1>Bad Gateway</h1>', { status: 502 }))
  await assert.rejects(musicApi('/search'), e => e.message.includes('502') && !e.message.includes('DOCTYPE') && !e.message.includes('Unexpected'))
})
test('music API rejects HTML success pages with a friendly error', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>proxy page</html>'))
  await assert.rejects(musicApi('/search'), /音乐接口响应异常/)
})
test('music API preserves structured backend errors and successful responses', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: '请切换平台' }, { status: 502 }))
  await assert.rejects(musicApi('/search'), /请切换平台/)
  fetch.mock.mockImplementation(async () => Response.json({ items: [] }))
  assert.deepEqual(await musicApi('/search'), { items: [] })
  fetch.mock.mockImplementation(async () => new Response(null, { status: 204 }))
  assert.equal(await musicApi('/lists/1', { method: 'DELETE' }), null)
})
test('music API preserves abort while consuming response body', async t => {
  const error = new DOMException('aborted', 'AbortError')
  t.mock.method(globalThis, 'fetch', async () => ({ status: 200, ok: true, text: async () => { throw error } }))
  await assert.rejects(musicApi('/search'), e => e.name === 'AbortError')
})

test('music API distinguishes retryable gateway failures from backend exhaustion', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response('<html>gateway</html>', { status: 502 }))
  await assert.rejects(musicApi('/resolve'), e => e.status === 502 && e.retryable && e.gateway)
  fetch.mock.mockImplementation(async () => Response.json({ detail: '已尝试所有音源' }, { status: 502 }))
  await assert.rejects(musicApi('/resolve'), e => e.status === 502 && e.retryable && !e.gateway)
  fetch.mock.mockImplementation(async () => Response.json({ detail: '操作频繁' }, { status: 429 }))
  await assert.rejects(musicApi('/search'), e => e.status === 429 && !e.retryable)
})

test('network failure and timer timeout are retryable, user cancellation is not', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('network') })
  await assert.rejects(musicApi('/search'), e => e.retryable === true)
  fetch.mock.mockImplementation(async (_url, options) => new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException('aborted', 'AbortError'))
    if (options.signal.aborted) abort()
    else options.signal.addEventListener('abort', abort, { once: true })
  }))
  await assert.rejects(musicApi('/search', { timeout: 2 }), e => e.name === 'AbortError' && e.retryable === true)
  const controller = new AbortController(); controller.abort()
  await assert.rejects(musicApi('/search', { signal: controller.signal }), e => e.name === 'AbortError' && !e.retryable)
})
