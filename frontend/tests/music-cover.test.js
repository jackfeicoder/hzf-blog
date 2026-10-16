import test from 'node:test'
import assert from 'node:assert/strict'
import { coverUrl } from '../src/music/cover.js'

test('missing album art stays a placeholder without making a request', () => {
  for (const song of [null,undefined,{},{source:'wy',id:'123',pic_id:''}]) assert.equal(coverUrl(song),'')
})

test('mini and fullscreen art share the existing cached, same-origin cover endpoint', () => {
  const song={source:'kg',id:'song_hash',pic_id:'cover_hash'}
  assert.equal(coverUrl(song),'/api/music/cover?source=kg&id=cover_hash&song_id=song_hash')
  assert.equal(coverUrl({...song,name:'long title'}),coverUrl(song))
})
