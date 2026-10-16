import { useState } from 'react'
import { coverUrl } from './cover'

export default function CoverArt({ song, className = '' }) {
  const url = coverUrl(song)
  const [failedUrl, setFailedUrl] = useState('')
  return <span className={`music-cover-art ${className}`}>
    {url && failedUrl !== url ? <img src={url} alt={`${song.name}封面`} loading="lazy" decoding="async" fetchPriority="low" onError={() => setFailedUrl(url)} /> : <span aria-hidden="true">♫</span>}
  </span>
}
