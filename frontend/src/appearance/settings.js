export const DEFAULT_APPEARANCE = Object.freeze({ theme: 'light', palette: 'warm', background: 'aurora',
  background_url: '', cursor: 'system', click_effect: 'ripple', motion: true, glass_transparency: 11 })
const choices = { theme: ['light', 'dark'], palette: ['warm', 'ocean', 'forest', 'violet'],
  background: ['none', 'aurora', 'dawn', 'custom'], cursor: ['system', 'accent'], click_effect: ['ripple', 'stars', 'none'] }
export function validBackgroundURL(value) {
  if (typeof value !== 'string' || value.length > 500) return false
  // Relative local uploads or public HTTPS uploads; no data/blob/javascript,
  // credentials, query, CSS fragments, or arbitrary path content.
  if (/^\/uploads\/images\/\d{6}\/[a-f0-9]{32}\.(webp|png|jpe?g|gif)$/.test(value)) return true
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash
      && /^\/images\/\d{6}\/[a-f0-9]{32}\.(webp|png|jpe?g|gif)$/.test(url.pathname)
  } catch { return false }
}
export function normalizeAppearance(value) {
  const result = { ...DEFAULT_APPEARANCE }
  if (!value || typeof value !== 'object') return result
  for (const [key, allowed] of Object.entries(choices)) if (allowed.includes(value[key])) result[key] = value[key]
  result.motion = typeof value.motion === 'boolean' ? value.motion : true
  if (Number.isInteger(value.glass_transparency) && value.glass_transparency >= 0 && value.glass_transparency <= 80) result.glass_transparency = value.glass_transparency
  result.background_url = validBackgroundURL(value.background_url) ? value.background_url : ''
  if (result.background === 'custom' && !result.background_url) result.background = 'aurora'
  return result
}
// Shared key deliberately ignores all old per-account caches/dirty writes.
export const appearanceKey = () => 'blog_site_appearance_v2'
export const glassOpacity = settings => 1 - normalizeAppearance(settings).glass_transparency / 100
export function readAppearance(key, storage) {
  try { return normalizeAppearance(JSON.parse(storage.getItem(key))) } catch { return { ...DEFAULT_APPEARANCE } }
}
export function writeAppearance(key, value, storage) {
  try { storage.setItem(key, JSON.stringify(normalizeAppearance(value))) } catch { /* quota/private mode */ }
}
export function rippleAllowed(start, end, disabled, blocked) {
  return !disabled && !blocked && start && end.button === 0
    && Math.hypot(end.clientX - start.x, end.clientY - start.y) < 10
    && end.timeStamp - start.time < 700
}
