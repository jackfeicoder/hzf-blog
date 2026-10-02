import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../AuthContext'
import './media.css'

const emptyForm = { title: '', url: '', description: '', position: 0 }
const ordered = items => [...items].sort((a, b) => a.position - b.position || a.id - b.id)
function hostname(url) {
  try { return new URL(url).hostname } catch { return url }
}

export default function Videos() {
  const { user } = useAuth()
  const isAdmin = user?.username === 'jackfei'
  const [items, setItems] = useState(() => api.peekVideoLinks() || [])
  const [loading, setLoading] = useState(() => !api.peekVideoLinks())
  const [refreshing, setRefreshing] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [search, setSearch] = useState('')
  const [reload, setReload] = useState(0)
  const [editor, setEditor] = useState(null)
  const [saving, setSaving] = useState(false)
  const [deleteId, setDeleteId] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const titleInput = useRef(null)
  const revision = useRef(0)
  const busy = useRef(false)

  useEffect(() => {
    let active = true
    const version = revision.current
    const saved = api.peekVideoLinks()
    if (saved) setItems(saved)
    setLoading(!saved)
    setRefreshing(true)
    setLoadError('')
    api.videoLinks().then(data => {
      if (active && revision.current === version) setItems(data)
    }).catch(err => {
      if (active && revision.current === version) setLoadError(err.message)
    }).finally(() => {
      if (active) { setLoading(false); setRefreshing(false) }
    })
    return () => { active = false }
  }, [reload])

  useEffect(() => {
    setEditor(null)
    setDeleteId(null)
    setError('')
  }, [user?.username])

  useEffect(() => {
    if (editor) {
      titleInput.current?.focus()
      titleInput.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [editor?.id, !!editor])

  const filtered = useMemo(() => {
    const word = search.trim().toLocaleLowerCase()
    return items.filter(item => !word || `${item.title} ${item.description} ${hostname(item.url)}`.toLocaleLowerCase().includes(word))
  }, [items, search])

  function edit(item = emptyForm) {
    setError(''); setNotice(''); setDeleteId(null)
    setEditor({ ...item })
  }

  async function save(event) {
    event.preventDefault()
    if (!isAdmin || busy.current) return
    let parsed
    try { parsed = new URL(editor.url.trim()) } catch { /* handled below */ }
    if (!parsed || !['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
      setError('请输入完整的 http:// 或 https:// 网站链接'); return
    }
    busy.current = true; setSaving(true); setError(''); setNotice('')
    try {
      const saved = await api.saveVideoLink({ ...editor, title: editor.title.trim(), url: editor.url.trim(), position: Number(editor.position) })
      revision.current++
      setItems(prev => ordered([...prev.filter(item => item.id !== saved.id), saved]))
      setEditor(null); setNotice('链接已保存')
    } catch (err) { setError(err.message) }
    finally { busy.current = false; setSaving(false) }
  }

  async function remove(id) {
    if (!isAdmin || busy.current) return
    busy.current = true; setSaving(true); setError(''); setNotice('')
    try {
      await api.deleteVideoLink(id)
      revision.current++
      setItems(prev => prev.filter(item => item.id !== id))
      setDeleteId(null); setEditor(null); setNotice('链接已删除')
    } catch (err) { setError(err.message) }
    finally { busy.current = false; setSaving(false) }
  }

  return (
    <div className="media-page">
      <section className="panel media-hero">
        <div><div className="media-eyebrow">休闲时光</div><h1>看视频</h1><p>收藏值得打开的视频网站，选一个，开始放松。</p></div>
        {isAdmin && <button className="btn primary" disabled={saving || loading} onClick={() => edit()}>＋ 添加链接</button>}
      </section>

      {isAdmin && editor && <section className="panel media-editor" aria-labelledby="video-form-title">
        <h2 id="video-form-title">{editor.id ? '编辑链接' : '添加链接'}</h2>
        <form onSubmit={save}>
          <fieldset disabled={saving}>
            <div className="media-form-row">
              <label>名称<input ref={titleInput} required maxLength={80} value={editor.title} placeholder="例如：我的电影收藏" onChange={e => setEditor({ ...editor, title: e.target.value })} /></label>
              <label className="media-order">排序<input type="number" min="0" max="1000000" required value={editor.position} onChange={e => setEditor({ ...editor, position: e.target.value })} /><small>数字越小，越靠前</small></label>
            </div>
            <label>网站地址<input type="url" required maxLength={2000} value={editor.url} placeholder="https://example.com" onChange={e => setEditor({ ...editor, url: e.target.value })} /></label>
            <label>简介（选填）<textarea rows={2} maxLength={300} value={editor.description} placeholder="简单介绍这个网站" onChange={e => setEditor({ ...editor, description: e.target.value })} /></label>
            <div className="media-actions"><button type="submit" className="btn primary">{saving ? '正在保存…' : '保存链接'}</button><button type="button" className="btn ghost" onClick={() => { setEditor(null); setError('') }}>取消</button></div>
          </fieldset>
        </form>
      </section>}

      <div className="media-feedback" aria-live="polite">{notice}</div>
      {error && <div className="media-error" role="alert">{error}</div>}
      {loadError && <div className="media-error" role="alert"><span>{loadError}{items.length > 0 && '，暂时显示上次加载的链接。'}</span><button className="btn ghost sm" onClick={() => { api.refreshVideoLinks(); setReload(n => n + 1) }}>重新加载</button></div>}

      <section className="panel media-toolbar" aria-label="搜索视频链接">
        <span>{items.length} 个网站{refreshing && !loading && <small> · 正在更新</small>}</span>
        <div className="media-search"><input type="search" aria-label="搜索网站" placeholder="搜索网站名称、简介…" value={search} onChange={e => setSearch(e.target.value)} />{search && <button className="btn ghost sm" onClick={() => setSearch('')}>清空</button>}</div>
      </section>

      {loading && !items.length ? <div className="media-grid" aria-label="正在加载视频链接" aria-busy="true">{[0, 1, 2].map(n => <div className="panel media-skeleton" key={n}><div /><div /><div /></div>)}</div>
        : filtered.length ? <div className="media-grid">{filtered.map(item => <article key={item.id} className="panel media-card">
          <div className="media-card-head"><span className="media-icon" aria-hidden="true">▶</span><span className="media-host">{hostname(item.url)}</span></div>
          <h2><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a></h2>
          <p>{item.description || '打开网站，探索你喜欢的视频。'}</p>
          <a className="btn primary media-open" href={item.url} target="_blank" rel="noopener noreferrer" aria-label={`打开 ${item.title}（新标签页）`}>打开网站 <span aria-hidden="true">↗</span></a>
          {isAdmin && <div className="media-manage">{deleteId === item.id ? <>
            <span>确定删除这个链接？</span><button className="btn ghost sm media-delete" disabled={saving} onClick={() => remove(item.id)}>{saving ? '正在删除…' : '确认删除'}</button><button className="btn ghost sm" disabled={saving} onClick={() => setDeleteId(null)}>取消</button>
          </> : <><button className="btn ghost sm" disabled={saving} onClick={() => edit(item)}>编辑</button><button className="btn ghost sm media-delete" disabled={saving} onClick={() => { setDeleteId(item.id); setError('') }}>删除</button></>}</div>}
        </article>)}</div>
        : <section className="panel media-empty"><span className="media-empty-icon" aria-hidden="true">🎬</span><h2>{search ? '没有找到匹配的网站' : loadError ? '链接暂时加载失败' : '视频收藏，等你来填'}</h2><p>{search ? '换个关键词，或清空搜索看看。' : loadError ? '点击上方“重新加载”再试一次。' : isAdmin ? '点击“添加链接”，把喜欢的视频网站放进来。' : '管理员正在整理网站链接，稍后再来看看。'}</p>{search && <button className="btn ghost" onClick={() => setSearch('')}>清空搜索</button>}</section>}
      <p className="media-footnote">点击链接将在新标签页打开对应网站。</p>
    </div>
  )
}
