import { musicApi } from './api.js'
import { addToQueue, nextIndex, nextUnfailedIndex, parseLyrics, songKey } from './logic.js'
import { music } from './store.js'
import { bufferedRanges } from './seekGesture.js'
import { waitForRetry } from './retry.js'

export class MusicController {
  constructor(audio, request = musicApi, wait = waitForRetry) {
    this.wait = wait
    this.audio = audio; this.request = request; this.generation = 0; this.session = 0; this.desired = false; this.failures = []; this.attempts = 0; this.failedSongs = new Set()
    this.events = {
      timeupdate: () => { if (this.url) { this.lastPosition = audio.currentTime || 0; music.progress({ time: this.lastPosition }); if (!audio.paused && this.lastPosition - this.recoveryStart >= 3) this.failedSongs.clear() } },
      durationchange: () => music.progress({ duration: Number.isFinite(audio.duration) ? audio.duration : 0 }),
      progress: () => music.progress({ buffered: bufferedRanges(audio) }),
      seeked: () => { this.clearTimer(); if (this.desired && audio.readyState < 3) this.watchdog() },
      playing: () => { if (!this.desired) { audio.pause(); return } this.clearTimer(); music.set({ playing: true, status: 'playing', message: '' }); this.feedback('playing'); this.recordHistory() },
      pause: () => music.set({ playing: false }),
      ended: () => { if (this.desired) this.next(1, true) },
      error: () => { if (this.url && audio.getAttribute('src') === this.url && this.desired) this.fallback('error') },
      waiting: () => { if (this.desired && this.url) { music.set({ status: 'buffering' }); this.watchdog() } },
      loadedmetadata: () => { if (this.desired) this.resume() },
    }
    for (const [event, fn] of Object.entries(this.events)) audio.addEventListener(event, fn)
    try { const volume = Number(localStorage.getItem('music-volume')); if (localStorage.getItem('music-volume') !== null && Number.isFinite(volume)) this.volume(volume) } catch { /* optional preference */ }
    audio.volume = music.get().volume
    music.controller = this
  }
  clearTimer() { clearTimeout(this.timer); this.timer = null }
  watchdog() {
    if (this.timer || this.seekingPreview) return
    const generation = this.generation, position = this.audio.currentTime || 0
    this.timer = setTimeout(() => {
      this.timer = null
      if (!this.desired || generation !== this.generation) return
      if (!this.audio.paused && this.audio.currentTime > position + .25) { music.set({ status: 'playing', playing: true }); return }
      this.fallback('stalled')
    }, 20000)
  }
  feedback(event) {
    const token = this.url?.match(/^\/api\/music\/stream\/([\w-]+)$/)?.[1]
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
    ++this.generation; this.lyricGeneration = (this.lyricGeneration || 0) + 1; this.desired = false; this.abort?.abort(); this.lyricAbort?.abort(); this.clearTimer(); this.url = null; this.lastPosition = 0
    this.failedSongs = new Set(); this.skipMessage = ''; this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load()
    this.seekingPreview = false
    music.set({ playing: false, status: 'idle', sourceName: '', playbackSong: null, activeQuality: null, lyricsLoading: false }); music.progress({ time: 0, duration: 0, buffered: [] })
  }
  async play(song, queue, failedSongs = new Set()) {
    this.stop(); this.switching = false; this.pendingFailure = null; this.failures = []; this.attempted = []; this.deferred = []; this.refreshed = new Set(); this.attempts = 0; this.recorded = false; this.desired = true
    this.failedSongs = failedSongs; this.skipMessage = failedSongs.size ? '上一首暂无可用音源，正在自动尝试下一首…' : ''
    const existing = queue || music.get().queue
    music.set({ current: song, queue: existing.some(s => songKey(s) === songKey(song)) ? existing : [...existing, song], lyrics: [], translation: [], message: '', status: 'resolving' })
    this.lyrics(song); await this.resolve(song, this.generation)
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
    this.abort?.abort(); this.abort = new AbortController(); this.url = null
    music.set({ status: 'resolving', playing: false, message: gatewayRetry ? '音乐连接暂时中断，正在自动重试…' : this.failures.length ? '正在尝试下一个音源…' : this.skipMessage })
    try {
      const data = await this.request('/resolve', { method: 'POST', body: { song, quality: music.get().quality, attempted: this.attempted, deferred: this.deferred, refresh_token: refreshToken, allow_platform_fallback: true }, signal: this.abort.signal })
      if (generation !== this.generation) return
      this.deferred = data.deferred || this.deferred
      this.attempted = data.attempted || this.attempted; this.activeRoute = data.route_id || `${data.source_id}:${data.playback_song?.source || song.source}:${data.playback_song?.id || song.id}:${data.quality || music.get().quality}`
      this.url = data.url; this.seekAfterLoad = seek; this.lastPosition = seek; this.recoveryStart = seek
      this.audio.src = data.url; this.audio.load(); music.set({ sourceName: data.source_name, playbackSong: data.playback_song || song, activeQuality: data.quality || music.get().quality, status: this.desired ? 'buffering' : 'paused' })
      if (data.playback_song && songKey(data.playback_song) !== songKey(song)) this.lyrics(song, data.playback_song)
      if (this.desired) { this.watchdog(); await this.resume() }
    } catch (e) {
      if (generation !== this.generation) return
      // A transport error or batch budget never proves all interfaces failed.
      // Keep the candidate ledger across as many batches as the server needs.
      if (this.desired && e.continuation) {
        this.attempted = e.attempted || this.attempted
        this.deferred = e.deferred || this.deferred
        music.set({ message: e.retryAfter ? `部分接口暂未完成，等待 ${e.retryAfter} 秒后继续检测…` : `继续检测剩余音源与平台（第 ${continuation + 2} 批）…` })
        try { await this.wait((e.retryAfter || 0) * 1000, this.abort.signal) } catch { return }
        if (generation === this.generation && this.desired) return this.resolve(song, generation, seek, false, '', continuation + 1)
        return
      }
      if (!gatewayRetry && this.desired && e.retryable && (e.gateway || e instanceof TypeError || e.name === 'AbortError')) {
        music.set({ message: '音乐连接暂时中断，正在自动重试…' })
        return this.resolve(song, generation, seek, true, refreshToken, continuation)
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
    const generation = this.generation
    if (this.seekAfterLoad && Number.isFinite(this.audio.duration)) { this.audio.currentTime = Math.min(this.seekAfterLoad, Math.max(0, this.audio.duration - 0.2)); this.seekAfterLoad = 0 }
    try { await this.audio.play() }
    catch (e) {
      if (generation !== this.generation) return
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
    this.switching = true; this.clearTimer(); const generation = ++this.generation, seek = this.audio.currentTime || this.seekAfterLoad || this.lastPosition || 0
    const oldUrl = this.url, route = this.activeRoute
    this.feedback(reason)
    const refresh = !this.refreshed.has(route)
    if (refresh) { this.refreshed.add(route); this.attempted = this.attempted.filter(item => item !== route) }
    else { this.attempted = [...new Set([...this.attempted, route])]; this.failures.push(Number(route?.split(':')[0])) }
    const token = refresh ? oldUrl?.match(/^\/api\/music\/stream\/([\w-]+)$/)?.[1] || '' : ''
    this.audio.pause(); this.url = null
    ++this.attempts // Only explicit server exhaustion may skip the song.
    try { await this.resolve(music.get().current, generation, seek, false, token) }
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
    this.desired = true
    if (this.url) { this.watchdog(); this.resume() }
    else if (music.get().current) this.play(music.get().current)
    else if (music.get().queue.length) this.play(music.get().queue[0])
  }
  next(direction = 1, ended = false) {
    const state = music.get(), index = nextIndex(state.queue, state.current, state.mode, direction, ended)
    if (index >= 0) this.play(state.queue[index])
    else this.stop()
  }
  previewSeek(active) { this.seekingPreview = active; this.clearTimer(); if (!active && this.desired && music.get().status === 'buffering') this.watchdog() }
  seek(time) {
    if (!Number.isFinite(time) || !Number.isFinite(this.audio.duration)) return
    this.clearTimer()
    const position = Math.min(Math.max(0, time), this.audio.duration)
    this.lastPosition = position; this.recoveryStart = position; this.audio.currentTime = position
    music.progress({ time: position })
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
