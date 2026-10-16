import test, { afterEach, mock } from 'node:test'
import assert from 'node:assert/strict'
import { validateImage, imageDimensions, imageMarkdown, uploadImageFile, MAX_IMAGE_BYTES } from '../src/imageAssets.js'

afterEach(() => mock.restoreAll())
test('2 MiB ceiling and supported types checked before network', () => {
  validateImage({ size: MAX_IMAGE_BYTES, type: 'image/png' })
  for (const file of [null, { size: 0 }, { size: MAX_IMAGE_BYTES + 1, type: 'image/png' }, { size: 2, type: 'image/svg+xml' }]) assert.throws(() => validateImage(file))
})
test('dimensions reserve layout without query/cache-busting changes', () => {
  const markdown = imageMarkdown({ name: 'a[bad].png' }, { url: 'https://img.example/a.webp', width: 512, height: 300 })
  assert.match(markdown, /a bad .png/)
  assert.match(markdown, /a.webp#cb-size=512x300/)
  assert.deepEqual(imageDimensions('https://img.example/a.webp#cb-size=512x300'), { width: 512, height: 300 })
  for (const url of ['a#cb-size=0x2', 'a#cb-size=999999x2', 'a#cb-size=2x2"evil', 'old.png']) assert.equal(imageDimensions(url), null)
})
test('multipart upload authenticates without JSON Content-Type', async () => {
  const file = new Blob(['test'], { type: 'image/png' })
  mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/upload/image')
    assert.equal(options.headers.Authorization, 'Bearer fixture')
    assert.equal(options.headers['Content-Type'], undefined)
    assert.ok(options.body instanceof FormData)
    assert.ok(options.signal instanceof AbortSignal)
    return new Response(JSON.stringify({ url: 'https://img.example/one.webp' }))
  })
  assert.equal((await uploadImageFile('/api/upload/image', file, 'fixture')).url, 'https://img.example/one.webp')
})
test('anonymous, HTML gateway, and timeout failures have readable messages', async () => {
  const file = new Blob(['test'], { type: 'image/png' })
  await assert.rejects(uploadImageFile('/api/upload/image', file, ''), /登录/)
  mock.method(globalThis, 'fetch', async () => new Response('<!DOCTYPE html>', { status: 502 }))
  await assert.rejects(uploadImageFile('/api/upload/image', file, 'fixture'), error => error.status === 502 && !error.message.includes('Unexpected token'))
  mock.method(globalThis, 'fetch', async () => { throw new DOMException('Aborted', 'AbortError') })
  await assert.rejects(uploadImageFile('/api/upload/image', file, 'fixture'), /超时/)
})
