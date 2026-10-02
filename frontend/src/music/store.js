import { useSyncExternalStore } from 'react'
const listeners = new Set(), progressListeners = new Set()
const guestLists = () => [{ id: 'favorites', kind: 'favorites', name: '我喜欢', songs: [] }, { id: 'history', kind: 'history', name: '最近播放', songs: [] }]
let state = { current: null, queue: [], library: guestLists(), actor: null, libraryLoading: false, status: 'idle', playing: false,
  message: '', sourceName: '', mode: 'sequence', quality: '128k', volume: 0.7, lyrics: [], translation: [], lyricsLoading: false }
let progress = { time: 0, duration: 0 }
export const music = {
  controller: null,
  get: () => state,
  getProgress: () => progress,
  subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn) },
  subscribeProgress: fn => { progressListeners.add(fn); return () => progressListeners.delete(fn) },
  set: patch => { state = { ...state, ...patch }; listeners.forEach(fn => fn()) },
  progress: patch => { progress = { ...progress, ...patch }; progressListeners.forEach(fn => fn()) },
  guestLists,
}
export const useMusic = () => useSyncExternalStore(music.subscribe, music.get)
export const useMusicProgress = () => useSyncExternalStore(music.subscribeProgress, music.getProgress)
