// Drag previews never seek the audio element. Commit once for the current song.
export class SeekGesture {
  begin(song, value) { this.song = song; this.value = value; this.active = true }
  update(song, value) { if (this.active && song === this.song) this.value = value }
  finish(song, commit = true) {
    const value = this.active && song === this.song && commit ? this.value : null
    this.active = false; this.value = null
    return value
  }
}
// Native range thumbs travel between their half-width inset, not the box edges.
export function seekPosition(clientX, rect, duration, thumbWidth = 14) {
  if (!Number.isFinite(clientX) || !Number.isFinite(duration) || duration <= 0 || rect.width <= thumbWidth) return null
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left - thumbWidth / 2) / (rect.width - thumbWidth)))
  return Math.min(duration, Math.round(ratio * duration * 10) / 10)
}
export function bufferedRanges(audio) {
  const result = []
  if (!Number.isFinite(audio.duration) || audio.duration <= 0) return result
  for (let i = 0; i < (audio.buffered?.length || 0); i++) {
    result.push([Math.max(0, audio.buffered.start(i) / audio.duration * 100), Math.min(100, audio.buffered.end(i) / audio.duration * 100)])
  }
  return result
}
