import test from 'node:test'
import assert from 'node:assert/strict'
import { MUSIC_PLATFORMS, MUSIC_DEFAULT_SOURCE, MUSIC_DEFAULT_QUALITY, canManageMusicSources, musicDisplayName } from '../src/music/labels.js'
import { music } from '../src/music/store.js'

test('verified platform and standard quality are the default without changing IDs', () => {
  assert.equal(MUSIC_DEFAULT_SOURCE, 'kg')
  assert.equal(MUSIC_PLATFORMS[MUSIC_DEFAULT_SOURCE], '小狗')
  assert.equal(MUSIC_DEFAULT_QUALITY, '128k')
  assert.equal(music.get().quality, MUSIC_DEFAULT_QUALITY)
})

test('platform aliases preserve existing song identifiers', () => {
  assert.deepEqual(MUSIC_PLATFORMS, { wy: '小云', tx: '小Q', kw: '小酷', kg: '小狗', mg: '小咪' })
  assert.equal(Object.isFrozen(MUSIC_PLATFORMS), true)
})
test('source visibility uses the authenticated capability, not the legacy admin flag', () => {
  for (const user of [null, undefined, { username: 'alice' }, { username: 'other-admin', is_admin: true }]) {
    assert.equal(Boolean(canManageMusicSources(user)), false)
  }
  assert.equal(canManageMusicSources({ can_manage: true, is_admin: false }), true)
  assert.equal(canManageMusicSources({ username: 'jackfei', is_admin: true }), false)
})
test('imported source display names use the same aliases as search tabs', () => {
  assert.equal(musicDisplayName('网易云音乐 / QQ 音乐 / 酷我音乐 / 酷狗 / 咪咕'), '小云 / 小Q / 小酷 / 小狗 / 小咪')
  assert.equal(musicDisplayName('NetEase, QQ Music, Tencent, Kuwo, Kugou, Migu'), '小云, 小Q, 小Q, 小酷, 小狗, 小咪')
  assert.equal(musicDisplayName('自定义音源 v2'), '自定义音源 v2')
  assert.equal(musicDisplayName(null), '')
})
