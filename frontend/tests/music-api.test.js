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
