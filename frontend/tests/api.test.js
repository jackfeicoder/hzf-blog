import test, { beforeEach, afterEach, mock } from 'node:test'
import assert from 'node:assert/strict'
import { api, clearToken, setToken, invalidatePublicCache } from '../src/api.js'

function storage() {
  const data = new Map()
  return { getItem: key => data.get(key) || null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) }
}
let calls
beforeEach(() => {
  globalThis.localStorage = storage()
  globalThis.sessionStorage = storage()
  calls = []
  invalidatePublicCache()
  mock.method(globalThis, 'fetch', async (path, options) => {
    calls.push({ path, options })
    return new Response(JSON.stringify({ call: calls.length, items: [] }), { status: 200 })
  })
})
afterEach(() => mock.restoreAll())

test('home requests share cached responses with sidebars', async () => {
  await Promise.all([api.listPosts(), api.listPosts()])
  await api.listPosts()
  assert.equal(calls.length, 1)
  assert.equal(api.peekPosts().call, 1)
  await api.listCategories(); await api.listCategories()
  await api.hotPosts(8); await api.hotPosts(8)
  await api.topAuthors(6); await api.topAuthors(6)
  assert.equal(calls.length, 4)
})
test('filters and sorting have distinct cache keys', async () => {
  await api.listPosts({ search: 'java' })
  await api.listPosts({ search: 'python' })
  await api.listPosts({ sort: 'hot' })
  assert.equal(calls.length, 3)
})
test('auth changes clear cache, including external token changes', async () => {
  await api.listPosts()
  setToken('account-a')
  assert.equal(api.peekPosts(), undefined)
  await api.listPosts()
  assert.equal(calls[1].options.headers.Authorization, 'Bearer account-a')
  localStorage.setItem('blog_token', 'account-b')
  assert.equal(api.peekPosts(), undefined)
  await api.listPosts()
  clearToken()
  assert.equal(api.peekPosts(), undefined)
  await api.listPosts()
  assert.equal(calls.length, 4)
})
test('post mutations invalidate public lists', async () => {
  await api.listPosts()
  await api.likePost(1)
  assert.equal(api.peekPosts(), undefined)
  await api.listPosts()
  assert.equal(calls.length, 3)
})
test('draft-capable author queries and private study queries are never cached', async () => {
  await api.listPosts({ author: 'alice' }); await api.listPosts({ author: 'alice' })
  await api.studyToday(); await api.studyToday()
  assert.equal(calls.length, 4)
  assert.equal(api.peekPosts({ author: 'alice' }), undefined)
})
test('study mutations preserve unrelated public cache', async () => {
  await api.listPosts()
  await api.studyTask('task', { done: true })
  assert.equal(api.peekPosts().call, 1)
})
test('video reads share cache and edits invalidate it without dropping home cache', async () => {
  await api.listPosts()
  await Promise.all([api.videoLinks(), api.videoLinks()])
  assert.equal(calls.length, 2)
  assert.equal(api.peekVideoLinks().call, 2)
  await api.saveVideoLink({ id: 7, title: 'Updated', url: 'https://example.com', description: '', position: 0 })
  assert.equal(calls[2].options.method, 'PUT')
  assert.equal(JSON.parse(calls[2].options.body).id, undefined)
  assert.equal(api.peekVideoLinks(), undefined)
  assert.equal(api.peekPosts().call, 1)
  await api.videoLinks()
  mock.method(globalThis, 'fetch', async () => new Response(null, { status: 204 }))
  await api.deleteVideoLink(7)
  assert.equal(api.peekVideoLinks(), undefined)
})
test('successful 204 delete invalidates cache too', async () => {
  await api.listPosts()
  mock.method(globalThis, 'fetch', async () => new Response(null, { status: 204 }))
  assert.equal(await api.deletePost(1), null)
  assert.equal(api.peekPosts(), undefined)
})
test('HTTP errors expose status without caching failed responses', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('{"detail":"expired"}', { status: 401 }))
  await assert.rejects(api.me(), error => error.status === 401 && error.message === 'expired')
})
test('article delete sends confirmation password without storing it', async () => {
  setToken('test-token')
  await api.deletePost(1, 'local-test-password')
  assert.equal(calls[0].options.method, 'DELETE')
  assert.deepEqual(JSON.parse(calls[0].options.body), { password: 'local-test-password' })
  assert.equal(localStorage.getItem('password'), null)
  assert.equal(sessionStorage.getItem('password'), null)
})
test('admin reads never cache and admin writes invalidate public lists', async () => {
  await api.listPosts()
  await api.adminRequest('/users'); await api.adminRequest('/users')
  assert.equal(calls.length, 3)
  await api.adminRequest('/categories', { method: 'POST', body: { name: 'New' } })
  assert.equal(api.peekPosts(), undefined)
})
test('GET timeout has actionable error without aborting mutations', async () => {
  mock.method(globalThis, 'setTimeout', callback => { queueMicrotask(callback); return 123 })
  mock.method(globalThis, 'fetch', async (_, options) => new Promise((resolve, reject) => {
    if (!options.signal) resolve(new Response('{}'))
    else options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  await assert.rejects(api.me(), /加载超时/)
  await api.likePost(1)
})
