import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../AuthContext'
import { musicApi } from './api'
import { MUSIC_PLATFORMS as platforms, canManageMusicSources, musicDisplayName } from './labels'
export default function Sources() {
  const { user } = useAuth()
  return canManageMusicSources(user) ? <><SourceManager /><FileCacheManager /><RoutingDiagnostics /></> : null
}
function FileCacheManager() {
  const [data, setData] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const abort = useRef(null)
  useEffect(() => () => abort.current?.abort(), [])
  const load = async () => {
    abort.current?.abort(); abort.current = new AbortController(); setBusy(true); setError('')
    try { setData(await musicApi('/file-cache', { signal: abort.current.signal })) }
    catch (e) { if (e.name !== 'AbortError') setError(e.message) }
    finally { setBusy(false) }
  }
  const remove = async row => {
    if (!window.confirm(`清除“${row.title}”的歌曲文件缓存？下次播放会重新尝试缓存，收藏不受影响。`)) return
    setBusy(true); setError('')
    try { await musicApi(`/file-cache/${row.id}`, { method: 'DELETE' }); await load() }
    catch (e) { setError(e.message); setBusy(false) }
  }
  const size = value => `${(value / 1024**3).toFixed(2)} GB`
  return <section className="music-routing-diagnostics"><div className="music-section-head"><div><h2>歌曲文件缓存</h2><p>全站复用 · 标准音质优先 · 完整缓存后支持本机分段播放</p></div><button onClick={load} disabled={busy}>{busy ? '读取中…' : '查看 / 刷新缓存'}</button></div>
    {error && <div className="music-error" role="alert">{error}</div>}
    {data && <><p>{data.count} 首 · 已用 {size(data.bytes)} / {size(data.maximum)} · 磁盘剩余 {size(data.free)}</p><p>{data.status} · 待处理 {data.pending} · 低于 {size(data.minimum_free)} 暂停新增；容量满后按最近使用淘汰，最近播放中的文件受保护。</p>
      {data.items.map(row => <div className="music-source-row" key={row.id}><div><strong>{row.title}</strong><small>{row.singer} · {row.quality} · {(row.size / 1024**2).toFixed(1)} MB</small></div><button disabled={busy || row.pinned > Date.now()/1000} onClick={() => remove(row)}>{row.pinned > Date.now()/1000 ? '播放保护中' : '清除缓存'}</button></div>)}
      {!data.items.length && <p>还没有完整缓存，实际播放后会在后台缓存。</p>}</>}
  </section>
}
function RoutingDiagnostics() {
  const [data, setData] = useState(null), [loading, setLoading] = useState(false), [error, setError] = useState('')
  const abort = useRef(null)
  const load = async () => {
    abort.current?.abort(); abort.current = new AbortController(); setLoading(true); setError('')
    try { setData(await musicApi('/diagnostics', { signal: abort.current.signal })) }
    catch (e) { if (e.name !== 'AbortError') setError(e.message) }
    finally { setLoading(false) }
  }
  useEffect(() => () => abort.current?.abort(), [])
  const stage = { resolved: '地址解析', resolve_error: '地址解析', stream_ready: '音频验证', stream_error: '音频传输', playing: '浏览器播放', playback_error: '播放中断' }
  return <section className="music-routing-diagnostics"><div className="music-section-head"><div><h2>播放诊断</h2><p>成功路线长期记忆 · 分平台/音质自动优选 · 不改变手动排序和启停</p></div><button disabled={loading} onClick={load}>{loading ? '读取中…' : '查看 / 刷新日志'}</button></div>
    {error && <div className="music-error" role="alert">{error}</div>}
    {data && <><div className="music-source-row"><small>近 24 小时服务器实测统计；单首歌失败不会停用整个音源。日志不含播放地址、密钥或访客身份。</small></div>
      {data.health.map(row => <div className="music-source-row" key={`${row.source_id}:${row.platform}:${row.quality}`}><strong>{musicDisplayName(row.source_name)} · {platforms[row.platform]} · {row.quality}</strong><small>音频验证 {row.verified} 次 · 失败 {row.failures} 次</small></div>)}
      <div className="music-routing-events">{data.recent.slice(0, 30).map((row, i) => <div className="music-source-row" key={`${row.at}:${i}`}><div><strong>{row.title} <small>{row.singer}</small></strong><small>{musicDisplayName(row.source_name)} · {platforms[row.platform]} · {stage[row.stage] || row.stage} · {row.status === 'ok' ? '成功' : '失败'} {row.reason ? `(${row.reason})` : ''}</small></div><small>{new Date(row.at * 1000).toLocaleString()} · {row.elapsed_ms} ms</small></div>)}</div>
      {!data.recent.length && <div className="music-empty">还没有新版本的播放日志，实际播放后会记录</div>}</>}
  </section>
}
function SourceManager() {
  const { user } = useAuth(), admin = canManageMusicSources(user)
  const [rows, setRows] = useState([]), [busy, setBusy] = useState(''), [error, setError] = useState(''), [name, setName] = useState(''), [file, setFile] = useState(null)
  const controller = useRef(null), mounted = useRef(true), actor = useRef(user?.id)
  actor.current = user?.id
  const load = async () => { controller.current?.abort(); controller.current = new AbortController(); try { const result = await musicApi('/sources', { signal: controller.current.signal }); if (mounted.current) setRows(result.map(row => ({ ...row, name: musicDisplayName(row.name), status: musicDisplayName(row.status) }))) } catch (e) { if (mounted.current && e.name !== 'AbortError') setError(e.message) } }
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
