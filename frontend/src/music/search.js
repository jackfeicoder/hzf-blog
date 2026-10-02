import { musicApi } from './api.js'

const order = ['wy', 'kg', 'kw', 'mg', 'tx']
const cancelled = () => new DOMException('搜索已取消', 'AbortError')

// At most three requests: preferred platform, then two bounded backups.
// Cooldowns are session-local and contain no query or personal data.
export function createMusicSearch(request = musicApi, clock = Date.now) {
  const cooldowns = new Map()
  return async function search({ query, source, page = 1, signal, onAttempt = () => {} }) {
    if (signal?.aborted) throw cancelled()
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    const attempt = async (platform, backup = false) => {
      if (controller.signal.aborted) throw cancelled()
      onAttempt(platform)
      try {
        const data = await request(`/search?${new URLSearchParams({ q: query, source: platform, page })}`, { signal: controller.signal, timeout: 8000 })
        if (controller.signal.aborted) throw cancelled()
        if (!Array.isArray(data?.items) || data.items.some(song => song.source !== platform)) {
          throw Object.assign(new Error('搜索结果格式异常'), { retryable: true })
        }
        cooldowns.delete(platform)
        if (backup && !data.items.length) throw new Error('备用平台暂未找到歌曲')
        return { ...data, source: platform, switched: platform !== source }
      } catch (e) {
        if (!controller.signal.aborted && e.retryable) cooldowns.set(platform, clock() + 60000)
        throw e
      }
    }
    try {
      const backups = order.filter(p => p !== source && (cooldowns.get(p) || 0) <= clock()).slice(0, 2)
      if (page > 1 || (cooldowns.get(source) || 0) <= clock() || !backups.length) {
        try { return await attempt(source) }
        catch (e) {
          if (signal?.aborted) throw cancelled()
          // Never mix page 2+ with another platform's unrelated pagination.
          if (!e.retryable || page > 1 || !backups.length) throw e
        }
      }
      try { return await Promise.any(backups.map(p => attempt(p, true))) }
      catch {
        if (signal?.aborted) throw cancelled()
        throw new Error('已自动尝试备用平台，暂时都未找到可用结果，请稍后重试')
      }
    } finally {
      abort(); signal?.removeEventListener('abort', abort)
    }
  }
}

export const searchMusic = createMusicSearch()
