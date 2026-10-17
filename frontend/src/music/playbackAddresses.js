const KEY = 'music-file-addresses-v1'
const qualities = ['128k', '320k', 'flac', 'flac24bit']
const storage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) }
const identity = (song, quality) => JSON.stringify([song.source, song.id, song.name, song.singer || '', song.album || '', quality])
function clean(data) {
  if (!data?.file_cache_hit || !/^\/api\/music\/stream\/[a-f0-9]{64}$/.test(data.url) || !qualities.includes(data.quality)) return null
  return { url: data.url, quality: data.quality, file_cache_hit: true, cache_hit: true, source_id: 0, source_name: '本机缓存' }
}

// Remember only same-origin complete-file URLs, never expiring upstream URLs,
// provider secrets, account tokens, or personal playlist/history contents.
export class PlaybackAddresses {
  constructor(persistence = storage, maximum = 200) {
    this.storage = persistence; this.maximum = maximum; this.entries = new Map()
    try {
      const raw = this.storage.getItem(KEY)
      if (raw && raw.length < 1000000) {
        const rows = JSON.parse(raw)
        if (Array.isArray(rows)) for (const row of rows.slice(-maximum)) {
          if (!Array.isArray(row) || typeof row[0] !== 'string' || row[0].length > 1800) continue
          const value = clean(row[1]); if (value) this.entries.set(row[0], value)
        }
      }
    } catch { /* Memory cache still works when browser storage is unavailable. */ }
  }
  get(song, quality) { const value = this.entries.get(identity(song, quality)); return value ? { ...value } : null }
  forget(song, quality) {
    this.entries.delete(identity(song, quality))
    try { this.storage.setItem(KEY, JSON.stringify([...this.entries])) } catch { /* Optional persistence. */ }
  }
  put(song, quality, data, persist = true) {
    const value = clean(data)
    if (!value) return false
    const key = identity(song, quality)
    this.entries.delete(key); this.entries.set(key, value)
    while (this.entries.size > this.maximum) this.entries.delete(this.entries.keys().next().value)
    if (persist) this.persist()
    return true
  }
  persist() { try { this.storage.setItem(KEY, JSON.stringify([...this.entries])) } catch { /* Optional preference storage. */ } }
  seed(songs, entries) {
    if (!Array.isArray(entries) || entries.length > 500) return
    const byId = new Map(songs.map(song => [`${song.source}:${song.id}`, song]))
    for (const entry of entries) {
      const song = entry && byId.get(`${entry.source}:${entry.id}`)
      if (song) this.put(song, '128k', entry, false)
    }
    this.persist()
  }
}
export const playbackAddresses = new PlaybackAddresses()
