import { useEffect, useRef, useState } from 'react'
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
export function PlaybackSettings({ onOpen }) {
  const s = useMusic(), [open, setOpen] = useState(false), root = useRef(null), trigger = useRef(null)
  useEffect(() => {
    if (!open) return
    const outside = e => { if (!root.current?.contains(e.target)) setOpen(false) }
    const escape = e => { if (e.key === 'Escape') { setOpen(false); trigger.current?.focus() } }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [open])
  const close = () => { setOpen(false); trigger.current?.focus() }
  return <div className="music-settings-wrap" ref={root}>
    <button ref={trigger} className={open ? 'active' : ''} aria-expanded={open} aria-haspopup="dialog" onClick={() => { if (!open) onOpen?.(); setOpen(!open) }}>⚙ 播放设置<small>{({ sequence: '顺序', shuffle: '随机', single: '单曲' })[s.mode]}</small></button>
    {open && <section className="music-settings-popover" role="dialog" aria-label="播放设置">
      <div className="music-section-head"><h3>播放设置</h3><button aria-label="关闭播放设置" onClick={close}>✕</button></div>
      <p>播放模式</p><div className="music-mode-options" role="group" aria-label="播放模式">{Object.entries({ sequence: '顺序播放', shuffle: '随机播放', single: '单曲循环' }).map(([value, label]) => <button key={value} aria-pressed={s.mode === value} className={s.mode === value ? 'active' : ''} onClick={() => music.controller?.mode(value)}>{label}</button>)}</div>
      <label className="music-settings-quality">播放音质<select aria-label="设置播放音质" value={s.quality} onChange={e => music.controller?.quality(e.target.value)}><option value="128k">标准 128k</option><option value="320k">高品 320k</option><option value="flac">无损 FLAC</option><option value="flac24bit">Hi-Res</option></select></label><small>音源不支持时自动降级</small>
    </section>}
  </div>
}
export function Volume({ label = '音量' }) {
  const s = useMusic()
  return <label className="music-volume"><span>音量</span><input aria-label={label} type="range" min="0" max="1" step=".01" value={s.volume} onChange={e => music.controller?.volume(e.target.value)} /><output>{Math.round(s.volume * 100)}%</output></label>
}
export default function PlayerBar() {
  const s = useMusic(), [queue, setQueue] = useState(false)
  const liked = s.library.find(l => l.kind === 'favorites')?.songs.some(song => songKey(song) === songKey(s.current))
  useEffect(() => { document.body.classList.toggle('has-music-player', !!s.current); return () => document.body.classList.remove('has-music-player') }, [!!s.current])
  if (!s.current) return null
  return <><div className="music-player-bar">
    <div className="music-now"><Link to="/music" className="music-mini-cover" aria-label="返回音乐播放器">♫</Link><div><Link to="/music" className="music-title">{s.current.name}</Link><small>{s.current.singer || '未知歌手'} · {s.sourceName || (s.status === 'resolving' ? '正在换源' : '待播放')}</small></div><button disabled={s.libraryLoading} aria-label={liked ? '取消喜欢' : '喜欢当前歌曲'} onClick={() => music.controller?.favorite(s.current)} className={liked ? 'is-liked' : ''}>{liked ? '♥' : '♡'}</button></div>
    <div className="music-transport"><Controls /><Progress /></div>
    <div className="music-extras"><PlaybackSettings onOpen={() => setQueue(false)} /><Volume /><button className={queue ? 'active' : ''} onClick={() => setQueue(!queue)} aria-expanded={queue}>≋ 播放队列 <span className="music-queue-count">{s.queue.length}</span></button></div>
  </div>{queue && <aside className="music-queue-popover panel"><div className="music-section-head"><h3>播放队列 · {s.queue.length}</h3><button onClick={() => music.controller?.clearQueue()}>清空</button><button aria-label="关闭队列" onClick={() => setQueue(false)}>✕</button></div><div className="music-queue-items">{s.queue.map(song => <div key={songKey(song)} className="music-queue-row"><button onClick={() => music.controller?.play(song)}>{song.name}<small>{song.singer}</small></button><button aria-label={`移除${song.name}`} onClick={() => music.controller?.removeQueue(song)}>✕</button></div>)}</div></aside>}</>
}
