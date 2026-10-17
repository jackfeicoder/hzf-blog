import test from 'node:test'
import assert from 'node:assert/strict'
import { PlaybackAddresses } from '../src/music/playbackAddresses.js'

const song = { source: 'kg', id: 'hash', name: '枫', singer: '周杰伦' }
const data = { url: '/api/music/stream/' + 'a'.repeat(64), file_cache_hit: true, quality: '128k' }
const storage = () => { let value; return { getItem: () => value, setItem: (key, next) => { value = next } } }

test('complete file addresses survive browser reopening without a time-based expiry', () => {
  const disk = storage(), first = new PlaybackAddresses(disk)
  assert.equal(first.put(song, '128k', data), true)
  const reopened = new PlaybackAddresses(disk)
  assert.equal(reopened.get(song, '128k').url, data.url)
  assert.equal(reopened.get(song, '320k'), null)
  assert.equal(reopened.get({ ...song, name: '枫 (Live)' }, '128k'), null)
  assert.equal(reopened.get({ ...song, singer: '另一歌手' }, '128k'), null)
})

test('external URLs, arbitrary paths and transient upstream tickets are never remembered', () => {
  const cache = new PlaybackAddresses(storage())
  for (const value of [
    { ...data, file_cache_hit: false }, { ...data, url: 'https://example.com/audio.mp3' },
    { ...data, url: '/api/music/stream/' + 'b'.repeat(43) }, { ...data, url: '/api/auth/me' },
    { ...data, quality: 'unknown' },
  ]) assert.equal(cache.put(song, '128k', value), false)
  assert.equal(cache.get(song, '128k'), null)
})

test('successful refreshed addresses replace old ones; invalid browser storage is harmless', () => {
  const disk = storage(), cache = new PlaybackAddresses(disk)
  cache.put(song, '128k', data)
  const updated = '/api/music/stream/' + 'b'.repeat(64)
  cache.put(song, '128k', { ...data, url: updated })
  assert.equal(new PlaybackAddresses(disk).get(song, '128k').url, updated)
  cache.forget(song, '128k'); assert.equal(new PlaybackAddresses(disk).get(song, '128k'), null)
  const denied = new PlaybackAddresses({ getItem() { throw new Error() }, setItem() { throw new Error() } })
  assert.equal(denied.put(song, '128k', data), true); assert.ok(denied.get(song, '128k'))
})

test('bounded address entries do not include extra fields or mutate returned data', () => {
  const disk = storage(), cache = new PlaybackAddresses(disk, 1)
  cache.put(song, '128k', { ...data, credential: 'never-store', playback_song: song })
  assert.equal(disk.getItem().includes('never-store'), false)
  cache.get(song, '128k').url = '/bad'
  assert.equal(cache.get(song, '128k').url, data.url)
  cache.put({ ...song, id: 'second' }, '128k', data)
  assert.equal(cache.get(song, '128k'), null)
})

test('public list seeds validated cache addresses once and does not seed private or unrelated songs', () => {
  let writes = 0
  const cache = new PlaybackAddresses({ getItem: () => null, setItem() { writes++ } })
  cache.seed([song], [{ ...data, source: song.source, id: song.id }, { ...data, source: 'wy', id: 'private-other' }])
  assert.equal(cache.get(song, '128k').url, data.url)
  assert.equal(cache.entries.size, 1); assert.equal(writes, 1)
  assert.equal(cache.get({ ...song, id: 'private-other' }, '128k'), null)
})
