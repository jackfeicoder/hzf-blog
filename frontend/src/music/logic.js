export const songKey = song => song ? `${song.source}:${song.id}` : ''
export const formatTime = value => { const s = Math.max(0, Math.floor(Number(value) || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` }
export function parseLyrics(text = '') {
  const lines = [], offset = Number(text.match(/\[offset:([+-]?\d+)\]/i)?.[1] || 0) / 1000
  for (const line of text.split(/\r?\n/)) {
    const tags = [...line.matchAll(/\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/g)]
    const content = line.replace(/\[[^\]]*\]/g, '').trim()
    if (!content) continue
    for (const tag of tags) lines.push({ time: Math.max(0, Number(tag[1]) * 60 + Number(tag[2]) + Number(`0.${tag[3] || 0}`) + offset), text: content })
  }
  return lines.sort((a, b) => a.time - b.time)
}
export function lyricIndex(lines, time) {
  let lo = 0, hi = lines.length - 1, found = -1
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (lines[mid].time <= time) { found = mid; lo = mid + 1 } else hi = mid - 1 }
  return found
}
export function nextIndex(queue, current, mode, direction = 1, ended = false, random = Math.random) {
  if (!queue.length) return -1
  const index = queue.findIndex(s => songKey(s) === songKey(current))
  if (mode === 'single' && ended && index >= 0) return index
  if (mode === 'shuffle' && queue.length > 1) {
    const choices = queue.map((_, i) => i).filter(i => i !== index)
    return choices[Math.floor(random() * choices.length)]
  }
  return (index + direction + queue.length) % queue.length
}
export function addToQueue(queue, song, current, next = false) {
  const copy = queue.filter(s => songKey(s) !== songKey(song))
  if (next) copy.splice(Math.max(0, copy.findIndex(s => songKey(s) === songKey(current)) + 1), 0, song)
  else copy.push(song)
  return copy
}
