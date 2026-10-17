import { musicApi } from './api.js'
import { waitForRetry } from './retry.js'

export const RECOMMENDATION_KEY = 'music-public-recommendation-v1'
const storage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) }
function clean(value) {
  if (!value || !Array.isArray(value.songs) || value.songs.length > 500) throw new Error('推荐歌单格式异常，请稍后重试')
  const songs = value.songs.map(song => {
    if (!song || !['wy', 'tx', 'kw', 'kg', 'mg'].includes(song.source) || !/^[\w-]{1,160}$/.test(song.id) || typeof song.name !== 'string' || !song.name.trim()) throw new Error('推荐歌曲格式异常')
    const text = (key, max) => String(song[key] || '').slice(0, max)
    return { source: song.source, id: String(song.id), name: text('name', 200), singer: text('singer', 300), album: text('album', 300),
      pic_id: /^[\w-]{0,160}$/.test(song.pic_id || '') ? song.pic_id || '' : '', lyric_id: /^[\w-]{0,160}$/.test(song.lyric_id || '') ? song.lyric_id || '' : '',
      duration: Number.isFinite(Number(song.duration)) ? Math.max(0, Math.min(86400, Number(song.duration))) : 0 }
  })
  return { name: '管理员的歌单', owner: 'administrator', songs }
}

// Public recommendations only. Personal favorites/history are never stored here.
export class RecommendationFeed {
  constructor(request = musicApi, options = {}) {
    this.request = request; this.storage = options.storage || storage; this.wait = options.wait || waitForRetry; this.now = options.now || Date.now
    this.value = null; this.nextRefresh = 0; this.failures = 0; this.flight = null
    try { const cached = this.storage.getItem(RECOMMENDATION_KEY); if (cached && cached.length < 1500000) this.value = clean(JSON.parse(cached)) } catch { /* Optional, untrusted browser storage. */ }
  }
  shouldRefresh() { return !this.flight && this.now() >= this.nextRefresh }
  load(force = false) {
    if (this.flight) return this.flight
    if (!force && !this.shouldRefresh()) return Promise.resolve(this.value)
    const controller = this.controller = new AbortController()
    this.flight = Promise.resolve().then(async () => {
      try {
        let result
        for (let attempt = 0; attempt < 2; attempt++) {
          try { result = await this.request('/recommended', { signal: controller.signal, timeout: 15000 }); break }
          catch (error) {
            if (controller.signal.aborted || attempt || !(error.retryable || error instanceof TypeError)) throw error
            await this.wait(1500, controller.signal)
          }
        }
        if (controller.signal.aborted) throw new DOMException('读取已取消', 'AbortError')
        this.value = clean(result); this.failures = 0; this.nextRefresh = this.now() + 30000
        try { this.storage.setItem(RECOMMENDATION_KEY, JSON.stringify(this.value)) } catch { /* Quota/private mode must not hide valid data. */ }
        return this.value
      } catch (error) {
        if (!controller.signal.aborted) { this.failures++; this.nextRefresh = this.now() + Math.min(60000, 15000 * this.failures) }
        throw error
      } finally { if (this.controller === controller) { this.flight = null; this.controller = null } }
    })
    return this.flight
  }
  cancel() { this.controller?.abort(); this.controller = null; this.flight = null }
}
