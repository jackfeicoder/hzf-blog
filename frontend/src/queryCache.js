// Memory only: never persist private data or share responses across sessions.
export class QueryCache {
  constructor({ maxEntries = 80, staleMs = 5 * 60_000 } = {}) {
    this.entries = new Map()
    this.pending = new Map()
    this.version = 0
    this.maxEntries = maxEntries
    this.staleMs = staleMs
  }
  peek(key) {
    const entry = this.entries.get(key)
    if (!entry || Date.now() - entry.time > this.staleMs) return undefined
    return entry.data
  }
  read(key, fetcher, ttl = 30_000) {
    const entry = this.entries.get(key)
    if (entry && Date.now() - entry.time < ttl) return Promise.resolve(entry.data)
    if (this.pending.has(key)) return this.pending.get(key)
    const version = this.version
    const promise = Promise.resolve().then(fetcher).then(data => {
      if (version === this.version) {
        this.entries.delete(key)
        this.entries.set(key, { data, time: Date.now() })
        while (this.entries.size > this.maxEntries) this.entries.delete(this.entries.keys().next().value)
      }
      return data
    }).finally(() => {
      if (this.pending.get(key) === promise) this.pending.delete(key)
    })
    this.pending.set(key, promise)
    return promise
  }
  clear() {
    this.version++
    this.entries.clear()
    this.pending.clear()
  }
}
