export function bioParts(value = '') {
  const text = typeof value === 'string' ? value : ''
  const result = []
  const pattern = /https?:\/\/[^\s<>"'；;，,]+/gi
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const raw = match[0], url = raw.replace(/[。！？、）)\]】]+$/, '')
    let valid = false
    try {
      const parsed = new URL(url)
      valid = ['http:', 'https:'].includes(parsed.protocol) && !!parsed.hostname && !parsed.username && !parsed.password
    } catch { /* render malformed URLs as text */ }
    if (!valid) continue
    if (match.index > cursor) result.push({ text: text.slice(cursor, match.index) })
    result.push({ text: url, href: url })
    cursor = match.index + url.length
  }
  if (cursor < text.length) result.push({ text: text.slice(cursor) })
  return result
}
