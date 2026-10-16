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
export function bufferedRanges(audio) {
  const result = []
  if (!Number.isFinite(audio.duration) || audio.duration <= 0) return result
  for (let i = 0; i < (audio.buffered?.length || 0); i++) {
    result.push([Math.max(0, audio.buffered.start(i) / audio.duration * 100), Math.min(100, audio.buffered.end(i) / audio.duration * 100)])
  }
  return result
}
