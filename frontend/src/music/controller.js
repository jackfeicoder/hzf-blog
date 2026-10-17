import { musicApi } from './api.js'
import { addToQueue, nextIndex, nextUnfailedIndex, parseLyrics, songKey } from './logic.js'
import { music } from './store.js'
import { bufferedRanges } from './seekGesture.js'
import { waitForRetry } from './retry.js'
import { cacheFileURL, playbackAddresses } from './playbackAddresses.js'

export class MusicController {
  constructor(audio, request = musicApi, wait = waitForRetry, addresses = playbackAddresses) {
    this.wait = wait; this.addresses = addresses
    this.audio = audio; this.request = request; this.generation = 0; this.session = 0; this.desired = false; this.failures = []; this.attempts = 0; this.failedSongs = new Set()
    this.events = {
      timeupdate: () => { if (this.url) {
        const position = audio.currentTime || 0
        if (!audio.seeking && position > this.lastPosition + .01) this.lastProgressAt = Date.now()
        this.lastPosition = position; music.progress({ time: position })
        if (!audio.seeking && !audio.paused && position - this.recoveryStart >= 3) { this.failedSongs.clear(); this.fileReconnects = 0; this.softRecovery = false }
      } },
      durationchange: () => music.progress({ duration: Number.isFinite(audio.duration) ? audio.duration : 0 }),
      progress: () => music.progress({ buffered: bufferedRanges(audio) }),
      seeked: () => { this.clearTimer(); if (this.desired && this.url) { this.watchdog(); if (audio.paused) this.resume() } },
      playing: () => {
        if (!this.desired) { audio.pause(); return }
        this.lastProgressAt = Date.now(); this.clearTimer(); music.set({ playing: true, status: 'playing', message: '' })
        const song = music.get().current
        if (song && this.fileCandidate) this.addresses.put(song, this.requestedQuality, this.fileCandidate)
        if (song && !this.isFileCached) this.warmFileAddress(song, this.generation)
        this.feedback('playing'); this.recordHistory(); this.watchdog()
      },
      pause: () => {
        if (audio.paused === false || (audio.ended && this.desired)) return // Ignore stale pauses and the natural-end pause preceding ended.
        music.set({ playing: false })
        // Respect a WebView/system pause; do not treat it as a broken source.
        if (this.desired && this.url && !this.switching) { this.desired = false; this.clearTimer(); music.set({ status: 'paused' }) }
      },
      ended: () => { if (this.desired && audio.ended !== false) this.next(1, true) },
      error: () => { if (this.url && audio.getAttribute('src') === this.url && this.desired) this.fallback('error') },
      waiting: () => { if (this.desired && this.url) { music.set({ status: 'buffering', playing: false }); this.watchdog() } },
      stalled: () => { if (this.desired && this.url) { music.set({ status: 'buffering', playing: false }); this.watchdog() } },
      seeking: () => { if (this.desired && this.url) { music.set({ status: 'buffering', playing: false }); this.watchdog() } },
      canplay: () => { if (this.desired && this.url) { this.watchdog(); if (audio.paused) this.resume() } },
      loadedmetadata: () => { if (this.desired) this.resume() },
    }
    for (const [event, fn] of Object.entries(this.events)) audio.addEventListener(event, fn)
    try { const volume = Number(localStorage.getItem('music-volume')); if (localStorage.getItem('music-volume') !== null && Number.isFinite(volume)) this.volume(volume) } catch { /* optional preference */ }
    audio.volume = music.get().volume
    music.controller = this
  }
  clearTimer() { clearTimeout(this.timer); this.timer = null }
  watchdog() {
    if (this.timer || this.seekingPreview || !this.desired || !this.url) return
    const generation = this.generation, position = this.audio.currentTime || 0
    this.lastProgressAt ??= Date.now()
    this.timer = setTimeout(() => {
      this.timer = null
      if (!this.desired || generation !== this.generation || !this.url) return
      const advanced = !this.audio.seeking && this.audio.currentTime > position + .05
      if (advanced) this.lastProgressAt = Date.now()
      const idle = Date.now() - this.lastProgressAt
      if (advanced && !this.audio.paused && this.audio.readyState >= 3) music.set({ status: 'playing', playing: true, message: '' })
      if (idle >= (this.isFileCached ? 12000 : 20000)) { this.fallback('stalled'); return }
      if (idle >= 8000 && !this.softRecovery && this.isFileCached) {
        // First let the existing download continue. play() does not discard
        // buffered bytes like src/load does, and it must not lock recovery.
        this.softRecovery = true
        music.set({ status: 'buffering', playing: false, message: '连接较慢，正在继续缓冲缓存歌曲…' })
        this.resume()
      }
      this.watchdog()
    }, 5000)
  }
  feedback(event) {
    const token = this.url?.match(/^\/api\/music\/stream\/([\w-]+)(?:\?[^#]*)?$/)?.[1]
    if (!token || (event === 'playing' && this.reportedToken === token)) return
    if (event === 'playing') this.reportedToken = token
    // Do not wait for telemetry on the playback/interaction critical path.
    this.request('/feedback', { method: 'POST', body: { token, event }, timeout: 4000 }).catch(() => {})
  }
  async actor(user) {
    const actor = user ? `${user.id}:${user.username}` : null
    if (music.get().actor === actor && this.actorInitialized) return
    this.actorInitialized = true
    const session = ++this.session
    this.stop(); this.libraryAbort?.abort(); this.mutations?.forEach(c => c.abort()); this.mutations = new Set()
    music.set({ actor, queue: [], current: null, lyrics: [], translation: [], library: music.guestLists(), libraryLoading: !!user, message: '' })
    if (!user) return
    this.libraryAbort = new AbortController()
    try {
      const library = await this.request('/library', { signal: this.libraryAbort.signal })
      if (session === this.session) { music.set({ library, libraryLoading: false }); if (music.get().playing) this.recordHistory() }
    } catch (e) { if (session === this.session) music.set({ libraryLoading: false, message: e.name === 'AbortError' ? '歌单读取超时，点击刷新歌单重试' : e.message }) }
  }
  async refreshLibrary() {
    if (!music.get().actor) return
    const session = this.session
    this.libraryAbort?.abort(); this.libraryAbort = new AbortController()
    music.set({ libraryLoading: true })
    try { const library = await this.request('/library', { signal: this.libraryAbort.signal }); if (session === this.session) music.set({ library, libraryLoading: false }) }
    catch (e) { if (session === this.session) music.set({ libraryLoading: false, message: e.message }) }
  }
  async mutation(path, options) {
    const controller = new AbortController(), session = this.session
    this.mutations ??= new Set(); this.mutations.add(controller)
    try { const result = await this.request(path, { ...options, signal: controller.signal }); if (session !== this.session) return; return result }
    finally { this.mutations.delete(controller) }
  }
  stop() {
    this.cacheAbort?.abort(); this.warmingGeneration = null; this.fileCandidate = null; this.cachedAttempt = false
    this.seekRevision = 0; this.seekTarget = null; this.seekAfterLoad = null
    ++this.generation; this.lyricGeneration = (this.lyricGeneration || 0) + 1; this.desired = false; this.abort?.abort(); this.lyricAbort?.abort(); this.clearTimer(); this.url = null; this.lastPosition = 0
    this.failedSongs = new Set(); this.skipMessage = ''; this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load()
    this.seekingPreview = false; this.lastProgressAt = null; this.isFileCached = false; this.fileReconnects = 0; this.softRecovery = false
    music.set({ playing: false, status: 'idle', sourceName: '', playbackSong: null, activeQuality: null, lyricsLoading: false }); music.progress({ time: 0, duration: 0, buffered: [] })
  }
  async play(song, queue, failedSongs = new Set()) {
    this.stop(); this.switching = false; this.pendingFailure = null; this.failures = []; this.attempted = []; this.deferred = []; this.refreshed = new Set(); this.attempts = 0; this.recorded = false; this.desired = true
    this.failedSongs = failedSongs; this.skipMessage = failedSongs.size ? '上一首暂无可用音源，正在自动尝试下一首…' : ''
    const existing = queue || music.get().queue
    this.requestedQuality = music.get().quality
    const cached = this.addresses.get(song, this.requestedQuality)
    music.set({ current: song, queue: existing.some(s => songKey(s) === songKey(song)) ? existing : [...existing, song], lyrics: [], translation: [], message: '', status: cached ? 'buffering' : 'resolving', sourceName: cached ? '本机缓存' : '正在读取播放地址' })
    if (cached) {
      // This is synchronous, inside the click gesture: no POST, HEAD, cache
      // preflight, or lyric request is allowed to delay assigning audio.src.
      this.cachedAttempt = true; this.startAudio(cached, song)
      this.lyrics(song)
      return
    }
    this.lyrics(song); await this.resolve(song, this.generation)
  }
  startAudio(data, song, seek = 0, connectionUrl = data.url) {
    this.deferred = data.deferred || this.deferred
    this.attempted = data.attempted || this.attempted
    this.activeRoute = data.route_id || `${data.source_id}:${data.playback_song?.source || song.source}:${data.playback_song?.id || song.id}:${data.quality || this.requestedQuality}`
    this.url = connectionUrl; this.seekAfterLoad = seek; this.lastPosition = seek; this.recoveryStart = seek
    this.isFileCached = data.file_cache_hit === true; this.lastProgressAt = Date.now(); this.softRecovery = false
    this.fileCandidate = this.isFileCached ? { ...data, url: connectionUrl } : null
    this.audio.src = connectionUrl; this.audio.load()
    music.progress({ time: seek, buffered: [] })
    music.set({ sourceName: data.source_name, playbackSong: data.playback_song || song, activeQuality: data.quality || this.requestedQuality, status: this.desired ? 'buffering' : 'paused' })
    if (this.desired) { this.watchdog(); this.resume() }
  }
  async warmFileAddress(song, generation) {
    if (this.warmingGeneration === generation) return
    this.warmingGeneration = generation; this.cacheAbort?.abort()
    const controller = this.cacheAbort = new AbortController(), quality = this.requestedQuality
    try {
      for (const delay of [5000, 15000, 30000, 90000]) {
        await waitForRetry(delay, controller.signal)
        if (generation !== this.generation) return
        try {
          // This endpoint only checks completed files; it never resolves sources.
          const data = await this.request('/cached', { method: 'POST', body: { song, quality }, signal: controller.signal, timeout: 6000 })
          if (generation !== this.generation || controller.signal.aborted) return
          if (data?.file_cache_hit) { this.addresses.put(song, quality, data); return }
        } catch { if (controller.signal.aborted) return }
      }
    } catch { /* Cancellation/network trouble must not interrupt current audio. */ }
  }
  async lyrics(song, playbackSong) {
    this.lyricAbort?.abort(); const generation = this.lyricGeneration = (this.lyricGeneration || 0) + 1
    this.lyricAbort = new AbortController(); music.set({ lyricsLoading: true })
    try {
      const data = await this.request('/lyrics/resolve', { method: 'POST', body: { song, ...(playbackSong ? { playback_song: playbackSong } : {}) }, signal: this.lyricAbort.signal, timeout: 16000 })
      if (generation === this.lyricGeneration) {
        const lines = parseLyrics(data.lyric)
        music.set({ ...(lines.length ? { lyrics: lines, translation: parseLyrics(data.translation) } : {}), lyricsLoading: false })
      }
    } catch { if (generation === this.lyricGeneration) music.set({ lyricsLoading: false }) }
  }
  async resolve(song, generation, seek = 0, gatewayRetry = false, refreshToken = '', continuation = 0) {
    const seekRevision = this.seekRevision
    this.abort?.abort(); this.abort = new AbortController(); this.url = null
    music.set({ status: this.isFileCached ? 'buffering' : 'resolving', playing: false, message: gatewayRetry ? '音乐连接暂时中断，正在自动重试…' : this.isFileCached ? '正在恢复缓存歌曲连接…' : this.failures.length ? '正在尝试下一个音源…' : this.skipMessage })
    try {
      const data = await this.request('/resolve', { method: 'POST', body: { song, quality: music.get().quality, attempted: this.attempted, deferred: this.deferred, refresh_token: refreshToken, allow_platform_fallback: true }, signal: this.abort.signal })
      if (generation !== this.generation) return
      if (this.cachedAttempt && !data.file_cache_hit) this.addresses.forget(song, this.requestedQuality)
      this.startAudio(data, song, this.seekRevision !== seekRevision ? this.seekTarget : seek)
      if (data.playback_song && songKey(data.playback_song) !== songKey(song)) this.lyrics(song, data.playback_song)
    } catch (e) {
      if (generation !== this.generation) return
      // A transport error or batch budget never proves all interfaces failed.
      // Keep the candidate ledger across as many batches as the server needs.
      if (this.desired && e.continuation) {
        this.attempted = e.attempted || this.attempted
        this.deferred = e.deferred || this.deferred
        music.set({ message: e.retryAfter ? `部分接口暂未完成，等待 ${e.retryAfter} 秒后继续检测…` : `继续检测剩余音源与平台（第 ${continuation + 2} 批）…` })
        try { await this.wait((e.retryAfter || 0) * 1000, this.abort.signal) } catch { return }
        if (generation === this.generation && this.desired) return this.resolve(song, generation, this.seekRevision !== seekRevision ? this.seekTarget : seek, false, '', continuation + 1)
        return
      }
      if (!gatewayRetry && this.desired && e.retryable && (e.gateway || e instanceof TypeError || e.name === 'AbortError')) {
        music.set({ message: '音乐连接暂时中断，正在自动重试…' })
        return this.resolve(song, generation, this.seekRevision !== seekRevision ? this.seekTarget : seek, true, refreshToken, continuation)
      }
      if (this.desired && e.exhausted === true) return this.failSong(song, generation)
      if (!this.desired) { music.set({ status: 'paused', playing: false }); return }
      this.clearTimer(); this.desired = false
      music.set({ status: 'error', playing: false, message: e.name === 'AbortError' ? '音源请求超时，请重试或切换平台' : e.message })
    }
  }
  async failSong(song, generation) {
    if (generation !== this.generation || !this.desired) return
    const failedSongs = this.failedSongs
    failedSongs.add(songKey(song))
    const state = music.get(), index = nextUnfailedIndex(state.queue, song, failedSongs, state.mode)
    if (index >= 0) return this.play(state.queue[index], undefined, failedSongs)
    this.stop()
    music.set({ status: 'error', playing: false, message: '本轮播放队列中的歌曲均尝试失败，已暂停。可重试播放或更换歌单。' })
  }
  async resume() {
    if (!this.url || !this.desired) return
    const generation = this.generation, url = this.url
    try {
      if (this.seekAfterLoad !== null && this.seekAfterLoad !== undefined && this.audio.readyState !== 0 && Number.isFinite(this.audio.duration)) {
        this.audio.currentTime = Math.min(this.seekAfterLoad, Math.max(0, this.audio.duration - 0.2)); this.seekAfterLoad = null
      }
      await this.audio.play()
    }
    catch (e) {
      if (generation !== this.generation || url !== this.url) return
      if (e.name === 'NotAllowedError') { this.clearTimer(); this.desired = false; music.set({ status: 'paused', playing: false, message: '浏览器需要你再点一下播放按钮' }) }
      else if (e.name !== 'AbortError') this.fallback()
    }
  }
  async fallback(reason = 'error') {
    if (!this.desired || !music.get().current) return
    if (this.switching) {
      if (this.url) this.pendingFailure = { generation: this.generation, url: this.url, reason }
      return
    }
    if (this.isFileCached && (this.fileReconnects || 0) >= 2) {
      this.desired = false; this.clearTimer(); this.audio.pause()
      music.set({ status: 'error', playing: false, message: '当前连接持续中断，歌曲缓存仍保留。请点播放重试。' })
      return
    }
    if (this.isFileCached) this.fileReconnects = (this.fileReconnects || 0) + 1
    this.switching = true; this.clearTimer()
    const generation = ++this.generation, seekRevision = this.seekRevision
    const seek = this.seekAfterLoad ?? (Number.isFinite(this.audio.currentTime) ? this.audio.currentTime : this.lastPosition || 0)
    const oldUrl = this.url, route = this.activeRoute
    const cachedFile = this.isFileCached && this.fileCandidate && cacheFileURL(this.fileCandidate.url) ? this.fileCandidate : null
    this.feedback(reason)
    const refresh = !this.refreshed.has(route)
    if (refresh) { this.refreshed.add(route); this.attempted = this.attempted.filter(item => item !== route) }
    else if (!this.isFileCached) { this.attempted = [...new Set([...this.attempted, route])]; this.failures.push(Number(route?.split(':')[0])) }
    const token = refresh ? oldUrl?.match(/^\/api\/music\/stream\/([\w-]+)(?:\?[^#]*)?$/)?.[1] || '' : ''
    this.audio.pause(); this.url = null
    ++this.attempts // Only explicit server exhaustion may skip the song.
    try {
      if (cachedFile) {
        let data = cachedFile
        // The first retry reconnects the complete file immediately. Only a
        // subsequent failure needs a bounded cache-index check, never 2x32s.
        if (this.fileReconnects > 1) {
          this.abort?.abort(); this.abort = new AbortController()
          try {
            data = await this.request('/cached', { method: 'POST', body: { song: music.get().current, quality: this.requestedQuality }, signal: this.abort.signal, timeout: 4000 })
          } catch {
            if (generation !== this.generation) return
            if (!this.desired) { music.set({ status: 'paused', playing: false }); return }
            this.desired = false; this.clearTimer()
            music.set({ status: 'error', playing: false, message: '缓存连接暂时没有响应，歌曲文件仍保留。请点播放重试。' })
            return
          }
          if (generation !== this.generation) return
          if (data === null) {
            // A successful cache-only miss, not a mobile timeout, establishes
            // that resolving upstream is necessary. Never delete audio files.
            this.addresses.forget(music.get().current, this.requestedQuality)
            this.isFileCached = false; this.fileCandidate = null
            return await this.resolve(music.get().current, generation, this.seekRevision !== seekRevision ? this.seekTarget : seek)
          }
          if (data?.file_cache_hit !== true || !cacheFileURL(data.url)) {
            this.desired = false; this.clearTimer()
            music.set({ status: 'error', playing: false, message: '缓存连接信息暂时异常，歌曲文件仍保留。请点播放重试。' })
            return
          }
        }
        if (generation !== this.generation) return
        const nonce = `${Date.now().toString(36)}-${this.connectionRevision = (this.connectionRevision || 0) + 1}`
        // Change the browser cache key only on failure, still addressing the
        // same signed file. Remember it only after actual playing succeeds.
        this.startAudio(data, music.get().current, this.seekRevision !== seekRevision ? this.seekTarget : seek, `${cacheFileURL(data.url)}?connection=${nonce}`)
        return
      }
      await this.resolve(music.get().current, generation, seek, false, token)
    }
    finally {
      if (generation === this.generation) {
        this.switching = false
        const pending = this.pendingFailure; this.pendingFailure = null
        if (pending?.generation === generation && pending.url === this.url && this.desired) {
          // A newly assigned URL may fail before play() settles. Do not drop
          // that error behind the switching lock and wait for the watchdog.
          queueMicrotask(() => { if (generation === this.generation && this.desired && pending.url === this.url) this.fallback(pending.reason) })
        }
      }
    }
  }
  toggle() {
    if (this.desired) { this.desired = false; this.clearTimer(); this.audio.pause(); music.set({ status: 'paused', playing: false }); return }
    if (music.get().status === 'error') { this.retry(); return }
    this.desired = true; this.lastProgressAt = Date.now(); this.softRecovery = false
    if (this.url) { this.watchdog(); this.resume() }
    else if (music.get().current) this.play(music.get().current)
    else if (music.get().queue.length) this.play(music.get().queue[0])
  }
  retry() {
    const song = music.get().current
    if (!song) return
    this.fileReconnects = 0; this.refreshed = new Set(); this.failures = []; this.attempted = []; this.deferred = []
    if (this.isFileCached && (this.url || this.fileCandidate)) { this.desired = true; return this.fallback('manual') }
    return this.play(song)
  }
  next(direction = 1, ended = false) {
    const state = music.get(), index = nextIndex(state.queue, state.current, state.mode, direction, ended)
    if (index >= 0) this.play(state.queue[index])
    else this.stop()
  }
  previewSeek(active) { this.seekingPreview = active; this.clearTimer(); if (!active && this.desired && this.url) this.watchdog() }
  seek(time) {
    const duration = Number.isFinite(this.audio.duration) ? this.audio.duration : music.getProgress().duration || music.get().current?.duration
    if (!Number.isFinite(time) || !Number.isFinite(duration) || duration <= 0) return
    this.clearTimer()
    const position = Math.min(Math.max(0, time), duration)
    this.seekRevision = (this.seekRevision || 0) + 1; this.seekTarget = position
    this.lastPosition = position; this.recoveryStart = position; this.lastProgressAt = Date.now(); this.softRecovery = false
    this.seekAfterLoad = position
    let seekFailed = false
    if (this.audio.readyState !== 0 && Number.isFinite(this.audio.duration)) {
      try { this.audio.currentTime = position; this.seekAfterLoad = null } catch { seekFailed = true }
    }
    music.progress({ time: position })
    if (music.get().status === 'error' && this.isFileCached && this.fileCandidate) {
      this.fileReconnects = 0; this.desired = true; this.fallback('manual'); return
    }
    if (seekFailed && this.desired) { this.fallback('error'); return }
    if (this.desired) this.watchdog()
  }
  volume(value) { const v = Math.min(1, Math.max(0, Number(value) || 0)); this.audio.volume = v; music.set({ volume: v }); try { localStorage.setItem('music-volume', v) } catch { /* optional */ } }
  mode(value) { const modes = ['sequence', 'shuffle', 'single']; if (value !== undefined && !modes.includes(value)) return; music.set({ mode: value ?? modes[(modes.indexOf(music.get().mode) + 1) % 3] }) }
  quality(value) { music.set({ quality: value }); if (music.get().current) this.play(music.get().current) }
  enqueue(song, next = false) { music.set({ queue: addToQueue(music.get().queue, song, music.get().current, next), message: next ? '已设为下一首' : '已加入播放队列' }) }
  removeQueue(song) { music.set({ queue: music.get().queue.filter(s => songKey(s) !== songKey(song)) }) }
  clearQueue() { this.stop(); music.set({ queue: [], current: null, lyrics: [], translation: [], message: '' }) }
  async updateList(listId, song, remove = false) {
    const session = this.session, state = music.get(), before = state.library.find(l => l.id === listId)
    if (!before || state.libraryLoading) return
    const lock = `${listId}:${songKey(song)}`
    this.locks ??= new Set(); if (this.locks.has(lock)) return
    this.locks.add(lock)
    const songs = before.songs.filter(s => songKey(s) !== songKey(song)); if (!remove) songs.unshift(song)
    music.set({ library: state.library.map(l => l.id === listId ? { ...l, songs: songs.slice(0, l.kind === 'history' ? 100 : 500) } : l) })
    try {
      if (state.actor) await this.mutation(`/lists/${listId}/songs${remove ? `?key=${encodeURIComponent(songKey(song))}` : ''}`, { method: remove ? 'DELETE' : 'PUT', ...(!remove ? { body: song } : {}) })
    } catch (e) {
      if (session === this.session) {
        // Roll back just this song, preserving unrelated concurrent edits.
        const old = before.songs.find(s => songKey(s) === songKey(song))
        music.set({ library: music.get().library.map(l => l.id === listId ? { ...l, songs: [...(old ? [old] : []), ...l.songs.filter(s => songKey(s) !== songKey(song))] } : l), message: e.message })
      }
    } finally { this.locks.delete(lock) }
  }
  favorite(song) { const list = music.get().library.find(l => l.kind === 'favorites'); if (list) this.updateList(list.id, song, list.songs.some(s => songKey(s) === songKey(song))) }
  recordHistory() { if (this.recorded || !music.get().current || music.get().libraryLoading) return; this.recorded = true; const l = music.get().library.find(l => l.kind === 'history'); if (l) this.updateList(l.id, music.get().current) }
  destroy() { this.stop(); ++this.session; this.libraryAbort?.abort(); this.mutations?.forEach(c => c.abort()); for (const [event, fn] of Object.entries(this.events)) this.audio.removeEventListener(event, fn); music.controller = null }
}
