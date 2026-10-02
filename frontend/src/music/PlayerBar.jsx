import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { music, useMusic, useMusicProgress } from './store'
import { formatTime, songKey } from './logic'
export function Progress() {
  const { time, duration } = useMusicProgress()
  return <div className="music-progress"><span>{formatTime(time)}</span><input type="range" aria-label="播放进度" min="0" max={duration || 1} step="0.1" value={Math.min(time, duration || 0)} disabled={!duration} onChange={e => music.controller?.seek(Number(e.target.value))} /><span>{formatTime(duration)}</span></div>
}
export function Controls() {
  const s = useMusic(), pending = ['resolving', 'buffering'].includes(s.status)
  return <div className="music-controls"><button aria-label="上一首" disabled={!s.queue.length} onClick={() => music.controller?.next(-1)}>⏮</button><button className="music-play" aria-label={s.playing || pending ? '暂停' : '播放'} disabled={!s.current && !s.queue.length} onClick={() => music.controller?.toggle()}>{s.playing || pending ? 'Ⅱ' : '▶'}</button><button aria-label="下一首" disabled={!s.queue.length} onClick={() => music.controller?.next()}>⏭</button></div>
}
export default function PlayerBar() {
  const s = useMusic(), [queue, setQueue] = useState(false)
  const liked = s.library.find(l => l.kind === 'favorites')?.songs.some(song => songKey(song) === songKey(s.current))
  useEffect(() => { document.body.classList.toggle('has-music-player', !!s.current); return () => document.body.classList.remove('has-music-player') }, [!!s.current])
  if (!s.current) return null
  return <><div className="music-player-bar">
    <div className="music-now"><Link to="/music" className="music-mini-cover" aria-label="返回音乐播放器">♫</Link><div><Link to="/music" className="music-title">{s.current.name}</Link><small>{s.current.singer || '未知歌手'} · {s.sourceName || (s.status === 'resolving' ? '正在换源' : '待播放')}</small></div><button disabled={s.libraryLoading} aria-label={liked ? '取消喜欢' : '喜欢当前歌曲'} onClick={() => music.controller?.favorite(s.current)} className={liked ? 'is-liked' : ''}>{liked ? '♥' : '♡'}</button></div>
    <div className="music-transport"><Controls /><Progress /></div>
    <div className="music-extras"><button title="切换播放模式" onClick={() => music.controller?.mode()}>{({ sequence: '顺序', shuffle: '随机', single: '单曲' })[s.mode]}</button><input aria-label="音量" title="音量" type="range" min="0" max="1" step="0.01" value={s.volume} onChange={e => music.controller?.volume(e.target.value)} /><button onClick={() => setQueue(!queue)} aria-expanded={queue}>队列 {s.queue.length}</button></div>
  </div>{queue && <aside className="music-queue-popover panel"><div className="music-section-head"><h3>播放队列 · {s.queue.length}</h3><button onClick={() => music.controller?.clearQueue()}>清空</button><button aria-label="关闭队列" onClick={() => setQueue(false)}>✕</button></div><div className="music-queue-items">{s.queue.map(song => <div key={songKey(song)} className="music-queue-row"><button onClick={() => music.controller?.play(song)}>{song.name}<small>{song.singer}</small></button><button aria-label={`移除${song.name}`} onClick={() => music.controller?.removeQueue(song)}>✕</button></div>)}</div></aside>}</>
}
