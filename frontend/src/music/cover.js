export function coverUrl(song) {
  return song?.pic_id ? `/api/music/cover?${new URLSearchParams({ source: song.source, id: song.pic_id, song_id: song.id })}` : ''
}
