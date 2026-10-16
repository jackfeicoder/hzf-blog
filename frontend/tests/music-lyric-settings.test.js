import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeLyricFont, readLyricFont, saveLyricFont, LYRIC_FONT_KEY } from '../src/music/lyricSettings.js'

test('lyric font is numeric, rounded and bounded; missing/corrupt values use default', () => {
  for (const value of [null,undefined,'',false,'broken',Infinity]) assert.equal(normalizeLyricFont(value),22)
  assert.equal(normalizeLyricFont('25.6'),26)
  assert.equal(normalizeLyricFont(1000),34)
  assert.equal(normalizeLyricFont(-10),14)
})
test('lyric size persists across visits without storing song or account information', () => {
  const values = new Map(), storage=()=>({getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)})
  assert.equal(readLyricFont(storage),22)
  assert.equal(saveLyricFont(28,storage),28)
  assert.equal(readLyricFont(storage),28)
  assert.deepEqual([...values],[[LYRIC_FONT_KEY,'28']])
})
test('blocked browser storage does not prevent manual changes or playback', () => {
  const blocked=()=>{throw Error('blocked')}
  assert.equal(readLyricFont(blocked),22)
  assert.equal(saveLyricFont(30,blocked),30)
})
