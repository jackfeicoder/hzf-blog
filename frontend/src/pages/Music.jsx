import { memo, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { musicApi } from '../music/api'
import { music, useMusic } from '../music/store'
import { lyricIndex, songKey } from '../music/logic'
import { Controls, Progress } from '../music/PlayerBar'
import Sources from '../music/Sources'
import '../music/music.css'

const platforms = { wy: '网易云', tx: 'QQ 音乐', kw: '酷我', kg: '酷狗', mg: '咪咕' }

function Cover({ song }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [songKey(song)])
  return <div className="music-cover">{song?.pic_id && !failed ? <img loading="lazy" src={`/api/music/cover?${new URLSearchParams({ source: song.source, id: song.pic_id, song_id: song.id })}`} alt={`${song.name}封面`} onError={() => setFailed(true)} /> : <span>♫</span>}</div>
}

const SongRow = memo(function SongRow({ song, index, current, liked, play, add, remove, disabled }) {
  return <div className={`music-song-row ${current ? 'current' : ''}`}>
    <button className="music-row-play" onClick={() => play(song)} aria-label={`播放${song.name}`}>{current ? '♫' : <><span>{String(index + 1).padStart(2, '0')}</span><i>▶</i></>}</button>
    <div className="music-song-info"><button onClick={() => play(song)} className="music-title">{song.name}</button><small>{song.singer || '未知歌手'}</small></div><span className="music-song-album">{song.album || '—'}</span>
    <div className="music-song-actions"><button className={liked ? 'is-liked' : ''} disabled={disabled} aria-label={`${liked ? '取消喜欢' : '喜欢'}${song.name}`} onClick={() => music.controller?.favorite(song)}>{liked ? '♥' : '♡'}</button><button title="下一首播放" aria-label={`下一首播放${song.name}`} onClick={() => music.controller?.enqueue(song, true)}>↳</button><button title="加入歌单" aria-label={`收藏${song.name}到歌单`} onClick={() => add(song)}>＋</button>{remove && <button title="从歌单移除" aria-label={`从歌单移除${song.name}`} onClick={() => remove(song)}>✕</button>}</div>
  </div>
})

function Lyrics() {
  const s = useMusic(), ref = useRef(null)
  // Only redraw lyrics when the active line changes, not on every progress tick.
  const index = useSyncExternalStore(music.subscribeProgress, () => lyricIndex(s.lyrics, music.getProgress().time))
  const [translation, setTranslation] = useState(true), lastScroll = useRef(0)
  const lines = useMemo(() => s.lyrics.map(line => ({ ...line, translated: translation ? s.translation.find(t => Math.abs(t.time - line.time) < .4)?.text : '' })), [s.lyrics, s.translation, translation])
  useEffect(() => {
    const panel = ref.current, active = panel?.querySelector('.active')
    if (active && Date.now() - lastScroll.current > 5000) panel.scrollTo({ top: Math.max(0, active.offsetTop - panel.clientHeight / 2 + active.clientHeight / 2), behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }, [index])
  return <section className="music-lyrics-panel"><div className="music-section-head"><h3>歌词</h3><button onClick={() => setTranslation(!translation)} aria-pressed={translation}>译 {translation ? '开' : '关'}</button></div><div ref={ref} className="music-lyrics" onWheel={() => { lastScroll.current = Date.now() }} onTouchMove={() => { lastScroll.current = Date.now() }}>
    {!s.current ? <p>挑一首歌，给今天一点旋律</p> : !s.lyrics.length ? <p>{s.lyricsLoading ? '正在寻找歌词…' : '暂无歌词，享受音乐吧'}</p> : lines.map((line, i) => <button key={`${line.time}:${i}`} className={i === index ? 'active' : ''} onClick={() => music.controller?.seek(line.time)}>{line.text}{line.translated && <small>{line.translated}</small>}</button>)}
  </div></section>
}

export default function Music() {
  const { user } = useAuth(), s = useMusic()
  const [view, setView] = useState('search'), [keyword, setKeyword] = useState(''), [source, setSource] = useState('wy'), [data, setData] = useState({ items: [], page: 1, has_more: false }), [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false), [error, setError] = useState(''), [modal, setModal] = useState(null), [listName, setListName] = useState(''), [saving, setSaving] = useState(false), [expanded, setExpanded] = useState(false)
  const abort = useRef(null), version = useRef(0), modalAbort = useRef(null), actorRef = useRef(s.actor)
  const selected = s.library.find(l => `list-${l.id}` === view)
  const songs = view === 'queue' ? s.queue : selected ? selected.songs : data.items
  const favorites = new Set(s.library.find(l => l.kind === 'favorites')?.songs.map(songKey) || [])
  useEffect(() => () => { ++version.current; abort.current?.abort(); modalAbort.current?.abort() }, [])
  useEffect(() => { actorRef.current = s.actor; setModal(null); setSaving(false); modalAbort.current?.abort(); if (view.startsWith('list-')) setView('search') }, [s.actor])
  const search = async (e, page = 1, platform = source, text = keyword) => {
    e?.preventDefault(); if (!text.trim()) return
    const current = ++version.current
    abort.current?.abort(); abort.current = new AbortController(); setLoading(true); setError(''); setView('search'); setQuery(text.trim())
    try { const result = await musicApi(`/search?${new URLSearchParams({ q: text.trim(), source: platform, page })}`, { signal: abort.current.signal, timeout: 12000 }); if (current === version.current) setData(result) }
    catch (e) { if (current === version.current) { setData({ items: [], page: 1, has_more: false }); setError(e.name === 'AbortError' ? '搜索超时，可以切换平台再试' : e.message) } }
    finally { if (current === version.current) setLoading(false) }
  }
  const editList = async e => {
    e.preventDefault(); if (!listName.trim() || saving) return
    const actor = s.actor; modalAbort.current = new AbortController(); setSaving(true); setError('')
    try {
      if (actor) await musicApi(modal.type === 'rename' ? `/lists/${modal.id}` : '/lists', { method: modal.type === 'rename' ? 'PUT' : 'POST', body: { name: listName.trim() }, signal: modalAbort.current.signal })
      else if (modal.type === 'rename') music.set({ library: music.get().library.map(l => l.id === modal.id ? { ...l, name: listName.trim() } : l) })
      else music.set({ library: [...music.get().library, { id: `guest-${Date.now()}`, kind: 'playlist', name: listName.trim(), songs: [] }] })
      if (actor === actorRef.current) { setModal(null); if (actor) music.controller?.refreshLibrary() }
    } catch (e) { if (actor === actorRef.current) setError(e.message) }
    finally { if (actor === actorRef.current) setSaving(false) }
  }
  const deleteList = async () => {
    if (!selected || !window.confirm(`删除歌单“${selected.name}”？`)) return
    const actor = s.actor, id = selected.id
    try { if (actor) await musicApi(`/lists/${id}`, { method: 'DELETE' }); if (actor === actorRef.current) { music.set({ library: music.get().library.filter(l => l.id !== id) }); setView('search') } }
    catch (e) { if (actor === actorRef.current) setError(e.message) }
  }
  return <div className={`music-page ${expanded ? 'music-expanded' : ''}`}>
    <aside className="music-sidebar"><div className="music-brand"><span>♫</span><div>音乐空间<small>让旋律陪你写代码</small></div></div><button className={view === 'search' ? 'active' : ''} onClick={() => setView('search')}>⌕ <span>发现音乐</span></button><p className="music-nav-label">我的音乐</p>
      {s.library.map(l => <button key={l.id} className={view === `list-${l.id}` ? 'active' : ''} onClick={() => { setView(`list-${l.id}`); setError('') }}><span>{l.kind === 'favorites' ? '♡' : l.kind === 'history' ? '◷' : '≡'}</span><span>{l.name}</span><small>{l.songs.length}</small></button>)}
      <button className={view === 'queue' ? 'active' : ''} onClick={() => setView('queue')}>≋ <span>播放队列</span><small>{s.queue.length}</small></button><button disabled={s.libraryLoading} onClick={() => { setListName(''); setModal({ type: 'create' }) }}>＋ <span>新建歌单</span></button><p className="music-nav-label">设置</p><button className={view === 'sources' ? 'active' : ''} onClick={() => setView('sources')}>⚙ <span>音源管理</span></button>{user && <button disabled={s.libraryLoading} onClick={() => music.controller?.refreshLibrary()}>↻ <span>{s.libraryLoading ? '同步歌单中…' : '刷新歌单'}</span></button>}
      {!user && <p className="music-guest-note">游客歌单暂存在本次访问中。<Link to="/login">登录</Link>后可保存到账号。</p>}
    </aside>
    <section className="music-main"><header className="music-heading"><div><span className="music-eyebrow">CODEBLOG MUSIC</span><h1>{view === 'sources' ? '我的音源' : selected ? selected.name : view === 'queue' ? '播放队列' : '发现好音乐'}</h1></div><button className="music-mobile-expand" onClick={() => setExpanded(!expanded)}>{expanded ? '收起播放器' : '展开播放器'}</button></header>
      {s.message && <div className={`music-notice ${s.status === 'error' ? 'music-error' : ''}`} role="status">{s.message}{s.status === 'error' && <button onClick={() => s.current && music.controller?.play(s.current)}>重试播放</button>}<button aria-label="关闭提示" onClick={() => music.set({ message: '' })}>✕</button></div>}{error && <div className="music-error" role="alert">{error}</div>}
      {view === 'sources' ? <Sources /> : <>
        {view === 'search' && <><form className="music-search" onSubmit={search}><span>⌕</span><input aria-label="搜索歌曲或歌手" placeholder="搜索歌曲、歌手，找到想听的声音" value={keyword} onChange={e => setKeyword(e.target.value)} maxLength={100} /><button className="btn primary" disabled={!keyword.trim()}>搜索</button></form><div className="music-platforms" role="group" aria-label="搜索平台">{Object.entries(platforms).map(([key, name]) => <button key={key} aria-pressed={source === key} className={source === key ? 'active' : ''} onClick={() => { setSource(key); if (query) search(null, 1, key, query) }}>{name}</button>)}</div></>}
        <div className="music-section-head"><div><h3>{selected ? `${songs.length} 首歌曲` : view === 'queue' ? `${songs.length} 首待播放` : query ? `“${query}”的搜索结果` : '听点什么？'}</h3><p>{loading ? '正在搜索，你仍可继续播放…' : selected ? '你的歌单，只属于你' : view === 'queue' ? '支持下一首插队，切换页面也能听' : '选择一个平台，输入歌名或歌手'}</p></div>{songs.length > 0 && <button className="btn ghost sm" onClick={() => music.controller?.play(songs[0], songs)}>▶ 全部播放</button>}{selected?.kind === 'playlist' && <><button onClick={() => { setListName(selected.name); setModal({ type: 'rename', id: selected.id }) }}>重命名</button><button onClick={deleteList}>删除歌单</button></>}</div>
        <div className="music-song-list" aria-busy={loading}>{songs.map((song, index) => <SongRow key={songKey(song)} song={song} index={index} current={songKey(s.current) === songKey(song)} liked={favorites.has(songKey(song))} disabled={s.libraryLoading} play={song => music.controller?.play(song, songs)} add={song => setModal({ type: 'add', song })} remove={selected ? song => music.controller?.updateList(selected.id, song, true) : view === 'queue' ? song => music.controller?.removeQueue(song) : null} />)}
          {!songs.length && <div className="music-empty"><div className="music-empty-note">♫</div><h3>{loading ? '正在寻找好音乐' : selected ? '歌单还很安静' : query ? '暂时没找到歌曲' : '今天，想听哪首歌？'}</h3><p>{loading ? '搜索不会中断当前播放' : selected ? '搜索后点 ♡ 喜欢，或 ＋ 加入歌单' : '搜索歌名或歌手，支持五个平台和自动换源'}</p>{!query && view === 'search' && <div className="music-suggestions">{['晴天', '陈奕迅', '纯音乐'].map(q => <button key={q} onClick={() => { setKeyword(q); search(null, 1, source, q) }}>{q} ↗</button>)}</div>}</div>}
        </div>{view === 'search' && query && <div className="music-pagination"><button disabled={data.page <= 1 || loading} onClick={() => search(null, data.page - 1, source, query)}>上一页</button><span>第 {data.page} 页</span><button disabled={!data.has_more || loading} onClick={() => search(null, data.page + 1, source, query)}>下一页</button>{loading && <button onClick={() => { ++version.current; abort.current?.abort(); setLoading(false) }}>取消搜索</button>}</div>}
      </>}
    </section>
    <aside className="music-detail"><button className="music-expanded-close" aria-label="收起播放器" onClick={() => setExpanded(false)}>✕</button><Cover song={s.current} /><h2>{s.current?.name || '随时，随地，随心听'}</h2><p>{s.current?.singer || '你的专属音乐角落'}</p><div className="music-quality"><label>播放音质 <select aria-label="播放音质" value={s.quality} onChange={e => music.controller?.quality(e.target.value)}><option value="128k">标准 128k</option><option value="320k">高品 320k</option><option value="flac">无损 FLAC</option><option value="flac24bit">Hi-Res</option></select></label><small>音源不支持时自动降级</small></div><Lyrics /><div className="music-detail-controls"><Controls /><Progress /><div className="music-full-extras"><button onClick={() => music.controller?.mode()}>{({ sequence: '顺序播放', shuffle: '随机播放', single: '单曲循环' })[s.mode]}</button><input aria-label="播放器音量" type="range" min="0" max="1" step=".01" value={s.volume} onChange={e => music.controller?.volume(e.target.value)} /><button onClick={() => { setView('queue'); setExpanded(false) }}>队列 {s.queue.length}</button></div>{s.message && <p role="status">{s.message}</p>}</div></aside>
    {modal && <div className="music-modal-backdrop" onClick={() => { if (!saving) setModal(null) }}><section className="music-modal panel" role="dialog" aria-modal="true" aria-label={modal.type === 'add' ? '加入歌单' : '歌单名称'} onClick={e => e.stopPropagation()} onKeyDown={e => { if (e.key === 'Escape' && !saving) setModal(null) }}><div className="music-section-head"><h3>{modal.type === 'add' ? '加入歌单' : modal.type === 'rename' ? '重命名歌单' : '新建歌单'}</h3><button aria-label="关闭" disabled={saving} onClick={() => setModal(null)}>✕</button></div>
      {modal.type === 'add' ? <div className="music-modal-lists">{s.library.filter(l => l.kind !== 'history').map(l => <button autoFocus={l.kind === 'favorites'} key={l.id} disabled={s.libraryLoading} onClick={() => { music.controller?.updateList(l.id, modal.song); setModal(null) }}>{l.name}<small>{l.songs.length} 首</small></button>)}<button onClick={() => { setListName(''); setModal({ type: 'create' }) }}>＋ 新建歌单</button></div> : <form onSubmit={editList}><input autoFocus aria-label="歌单名称" value={listName} onChange={e => setListName(e.target.value)} maxLength={60} required placeholder="给歌单起个名字" /><button className="btn primary" disabled={saving || !listName.trim()}>{saving ? '保存中…' : '保存'}</button></form>}
    </section></div>}
  </div>
}
