import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../AuthContext'
import { musicApi } from './api'
const platforms = { wy: '网易云', tx: 'QQ', kw: '酷我', kg: '酷狗', mg: '咪咕' }
export default function Sources() {
  const { user } = useAuth(), admin = user?.username === 'jackfei'
  const [rows, setRows] = useState([]), [busy, setBusy] = useState(''), [error, setError] = useState(''), [name, setName] = useState(''), [file, setFile] = useState(null)
  const controller = useRef(null), mounted = useRef(true), actor = useRef(user?.id)
  actor.current = user?.id
  const load = async () => { controller.current?.abort(); controller.current = new AbortController(); try { const result = await musicApi('/sources', { signal: controller.current.signal }); if (mounted.current) setRows(result) } catch (e) { if (mounted.current && e.name !== 'AbortError') setError(e.message) } }
  useEffect(() => { mounted.current = true; load(); return () => { mounted.current = false; controller.current?.abort() } }, [])
  const action = async (key, fn) => {
    if (busy) return
    const current = actor.current
    setBusy(key); setError('')
    try { await fn(); if (mounted.current && current === actor.current) await load() } catch (e) { if (mounted.current && current === actor.current) setError(e.message) }
    finally { if (mounted.current) setBusy('') }
  }
  const importFile = e => {
    e.preventDefault(); if (!file || !name.trim()) return
    if (file.size > 600000) { setError('音源文件最大 600 KB'); return }
    const form = e.target
    action('import', async () => { await musicApi('/sources', { method: 'POST', body: { name: name.trim(), script: await file.text() } }); if (mounted.current) { setName(''); setFile(null); form.reset() } })
  }
  return <section><div className="music-section-head"><div><h2>音源管理</h2><p>按优先级自动换源 · 失效源可关闭</p></div><button onClick={load}>刷新</button></div>
    <div className="music-notice">兼容测试验证脚本初始化，具体歌曲需实际播放测试。第三方音源可能要求自己的密钥，请先在本地编辑脚本；脚本仅存服务器，不会下发浏览器。</div>{error && <div className="music-error" role="alert">{error}</div>}
    {admin && <form className="music-source-import" onSubmit={importFile}><input aria-label="音源名称" placeholder="音源名称" value={name} onChange={e => setName(e.target.value)} maxLength={80} required /><input aria-label="音源脚本文件" type="file" accept=".js,.cjs,text/javascript" required onChange={e => { const f = e.target.files[0]; setFile(f); if (!name && f) setName(f.name.replace(/\.(c?js)$/i, '')) }} /><button className="btn primary" disabled={!!busy}>导入音源</button></form>}
    {!rows.length && <div className="music-empty">{admin ? '还没有音源，导入后先测试，再启用' : '管理员正在准备音源'}</div>}
    {rows.map(row => <article className="music-source-row" key={row.id}><div><h3>{row.name} <span className={`music-source-badge ${row.enabled ? 'enabled' : ''}`}>{row.enabled ? '已启用' : '未启用'}</span></h3><small>{row.status} · {Object.keys(row.capabilities).map(k => platforms[k]).join(' / ') || '待测试'}</small><small>SHA256 {row.digest.slice(0, 12)}…</small></div>
      {admin ? <div className="music-source-controls"><label>优先级<input type="number" aria-label={`${row.name}优先级`} min="0" max="999" defaultValue={row.position} key={`${row.id}:${row.position}`} disabled={!!busy} onBlur={e => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 0 && n <= 999 && n !== row.position) action(`priority-${row.id}`, () => musicApi(`/sources/${row.id}`, { method: 'PUT', body: { enabled: row.enabled, position: n } })) }} /></label><button disabled={!!busy} onClick={() => action(`test-${row.id}`, () => musicApi(`/sources/${row.id}/test`, { method: 'POST' }))}>{busy === `test-${row.id}` ? '测试中…' : '测试'}</button><button disabled={!!busy} onClick={() => action(`enable-${row.id}`, () => musicApi(`/sources/${row.id}`, { method: 'PUT', body: { enabled: !row.enabled, position: row.position } }))}>{row.enabled ? '关闭' : '启用'}</button><button disabled={!!busy} onClick={() => { if (window.confirm(`删除音源“${row.name}”？`)) action(`delete-${row.id}`, () => musicApi(`/sources/${row.id}`, { method: 'DELETE' })) }}>删除</button></div> : <small>优先级 {row.position}</small>}
    </article>)}
  </section>
}
