export const LYRIC_FONT_KEY = 'music-lyric-font-size-v1'
export const DEFAULT_LYRIC_FONT = 22
export const MIN_LYRIC_FONT = 14
export const MAX_LYRIC_FONT = 34

export function normalizeLyricFont(value) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return DEFAULT_LYRIC_FONT
  const size = Number(value)
  return Number.isFinite(size) ? Math.min(MAX_LYRIC_FONT, Math.max(MIN_LYRIC_FONT, Math.round(size))) : DEFAULT_LYRIC_FONT
}
export function readLyricFont(storage = () => localStorage) {
  try { return normalizeLyricFont(storage().getItem(LYRIC_FONT_KEY)) } catch { return DEFAULT_LYRIC_FONT }
}
export function saveLyricFont(value, storage = () => localStorage) {
  const size = normalizeLyricFont(value)
  try { storage().setItem(LYRIC_FONT_KEY, String(size)) } catch { /* Playback works even if storage is blocked. */ }
  return size
}
