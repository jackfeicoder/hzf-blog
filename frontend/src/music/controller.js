import { musicApi } from './api.js'
import { addToQueue, nextIndex, parseLyrics, songKey } from './logic.js'
import { music } from './store.js'

export class MusicController {
  constructor(audio, request = musicApi) {
    this.audio = audio; this.request = request; this.generation = 0; this.session = 0; this.desired = false; this.failures = []; this.attempts = 0
    this.events = {
      timeupdate: () => music.progress({ time: audio.currentTime || 0 }),
      durationchange: () => music.progress({ duration: Number.isFinite(audio.duration) ? audio.duration : 0 }),
      playing: () => { if (!this.desired) { audio.pause(); return } this.clearTimer(); music.set({ playing: true, status: 'playing', message: '' }); this.recordHistory() },
      pause: () => music.set({ playing: false }),
      ended: () => { if (this.desired) this.next(1, true) },
      error: () => { if (this.url && audio.getAttribute('src') === this.url && this.desired) this.fallback() },
      waiting: () => { if (this.desired && this.url) { music.set({ status: 'buffering' }); this.watchdog() } },
      loadedmetadata: () => { if (this.desired) this.resume() },
    }
    for (const [event, fn] of Object.entries(this.events)) audio.addEventListener(event, fn)
    try { const volume = Number(localStorage.getItem('music-volume')); if (localStorage.getItem('music-volume') !== null && Number.isFinite(volume)) this.volume(volume) } catch { /* optional preference */ }
    audio.volume = music.get().volume
    music.controller = this
  }
  clearTimer() { clearTimeout(this.timer) }
  watchdog() { this.clearTimer(); const generation = this.generation; this.timer = setTimeout(() => { if (this.desired && generation === this.generation) this.fallback() }, 10000) }
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
    ++this.generation; this.desired = false; this.abort?.abort(); this.lyricAbort?.abort(); this.clearTimer(); this.url = null
    this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load()
    music.set({ playing: false, status: 'idle', sourceName: '' }); music.progress({ time: 0, duration: 0 })
  }
  async play(song, queue) {
    this.stop(); this.failures = []; this.attempts = 0; this.recorded = false; this.desired = true
    const existing = queue || music.get().queue
    music.set({ current: song, queue: existing.some(s => songKey(s) === songKey(song)) ? existing : [...existing, song], lyrics: [], translation: [], message: '', status: 'resolving' })
    this.lyrics(song, this.generation); await this.resolve(song, this.generation)
  }
  async lyrics(song, generation) {
    this.lyricAbort = new AbortController(); music.set({ lyricsLoading: true })
    try {
      const data = await this.request(`/lyrics?${new URLSearchParams({ source: song.source, id: song.lyric_id || song.id })}`, { signal: this.lyricAbort.signal, timeout: 10000 })
      if (generation === this.generation) music.set({ lyrics: parseLyrics(data.lyric), translation: parseLyrics(data.translation), lyricsLoading: false })
    } catch { if (generation === this.generation) music.set({ lyricsLoading: false }) }
  }
  async resolve(song, generation, seek = 0) {
    this.abort?.abort(); this.abort = new AbortController(); this.url = null
    music.set({ status: 'resolving', playing: false, message: this.failures.length ? '正在尝试下一个音源…' : '' })
    try {
      const data = await this.request('/resolve', { method: 'POST', body: { song, quality: music.get().quality, exclude: this.failures }, signal: this.abort.signal })
      if (generation !== this.generation) return
      this.failures.push(data.source_id); this.url = data.url; this.seekAfterLoad = seek
      this.audio.src = data.url; this.audio.load(); music.set({ sourceName: data.source_name, status: this.desired ? 'buffering' : 'paused' })
      if (this.desired) { this.watchdog(); await this.resume() }
    } catch (e) {
      if (generation !== this.generation) return
      this.clearTimer(); this.desired = false
      music.set({ status: 'error', playing: false, message: e.name === 'AbortError' ? '音源请求超时，请重试或切换平台' : e.message })
    }
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
  async fallback() {
    if (!this.desired || this.switching || !music.get().current) return
    this.switching = true; this.clearTimer(); const generation = ++this.generation, seek = this.audio.currentTime || 0
    this.lyricAbort?.abort(); this.lyrics(music.get().current, generation)
    this.audio.pause(); this.url = null
    if (++this.attempts >= 4) { this.desired = false; music.set({ status: 'error', message: '这些音源暂时都未成功，可点重试或换平台' }); this.switching = false; return }
    try { await this.resolve(music.get().current, generation, seek) }
    finally { this.switching = false }
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
  seek(time) { if (Number.isFinite(this.audio.duration)) this.audio.currentTime = Math.min(Math.max(0, time), this.audio.duration) }
  volume(value) { const v = Math.min(1, Math.max(0, Number(value) || 0)); this.audio.volume = v; music.set({ volume: v }); try { localStorage.setItem('music-volume', v) } catch { /* optional */ } }
  mode() { const modes = ['sequence', 'shuffle', 'single']; music.set({ mode: modes[(modes.indexOf(music.get().mode) + 1) % 3] }) }
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
