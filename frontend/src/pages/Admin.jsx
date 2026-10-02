import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../AuthContext'
import PasswordConfirm from '../components/PasswordConfirm'
import './admin.css'

const tabs = [['posts', '文章'], ['users', '用户'], ['categories', '分类'], ['comments', '评论'], ['study', '用户打卡']]
const labels = { java: 'Java八股', hot100: 'Hot100', project: '项目学习' }
const monthNow = () => new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 7)

export default function Admin() {
  const { user } = useAuth()
  const allowed = user?.can_manage === true
  const [tab, setTab] = useState('posts')
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [edit, setEdit] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const version = useRef(0)
  const [users, setUsers] = useState([])
  const [userSearch, setUserSearch] = useState('')
  const [selectedUser, setSelectedUser] = useState('')
  const [month, setMonth] = useState(monthNow)
  const [study, setStudy] = useState(null)
  const [taskEdit, setTaskEdit] = useState(null)
  const studyVersion = useRef(0)

  const load = useCallback(async () => {
    if (!allowed || tab === 'study') return
    const current = ++version.current
    setLoading(true); setError('')
    try {
      const params = new URLSearchParams({ page, page_size: 20, search: query })
      const result = await api.adminRequest(`/${tab}?${params}`)
      if (version.current === current) setData(Array.isArray(result) ? { items: result, total: result.length } : result)
    } catch (e) { if (version.current === current) setError(e.message) }
    finally { if (version.current === current) setLoading(false) }
  }, [allowed, tab, page, query])
  useEffect(() => { setData({ items: [], total: 0 }); load(); return () => { version.current++ } }, [load])
  useEffect(() => {
    if (!allowed || tab !== 'study') return
    let active = true
    api.adminRequest('/users?page_size=50').then(r => { if (active) setUsers(r.items) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false; studyVersion.current++ }
  }, [allowed, tab])

  const studyLoad = async (target = selectedUser) => {
    if (!target) return
    const current = ++studyVersion.current
    setLoading(true); setError(''); setStudy(null); setTaskEdit(null)
    try {
      const root = `/users/${target}/study`
      // Creating today's snapshot is an explicit admin action, not list-page prefetch.
      const day = await api.adminRequest(`${root}/today`)
      const [progress, history] = await Promise.all([api.adminRequest(`${root}/progress`), api.adminRequest(`${root}/history?month=${encodeURIComponent(month)}`)])
      if (current === studyVersion.current) setStudy({ userId: target, month, day, progress, history })
    } catch (e) { if (current === studyVersion.current) setError(e.message) }
    finally { if (current === studyVersion.current) setLoading(false) }
  }
  const mutate = async (fn) => {
    if (busy) return
    setBusy(true); setError(''); setMessage('')
    try { await fn(); setEdit(null); setMessage('已保存'); await load() }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  const changeTab = value => {
    version.current++; studyVersion.current++
    setTab(value); setPage(1); setSearch(''); setQuery(''); setEdit(null); setError(''); setMessage(''); setLoading(false); setTaskEdit(null); setStudy(null)
  }
  const saveEdit = event => {
    event.preventDefault()
    mutate(async () => {
      const { id, ...body } = edit
      await api.adminRequest(`/${tab}${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', body })
    })
  }
  const remove = async password => {
    const target = deleting
    if (target.kind === 'posts') await api.deletePost(target.id, password)
    else await api.adminRequest(target.kind === 'study' ? `/users/${target.id}/study` : `/users/${target.id}`, { method: 'DELETE', body: { password } })
    setDeleting(null); setMessage('已删除')
    if (target.kind === 'study') { setStudy(null); setTaskEdit(null) }
    else await load()
  }
  if (!user) return <div className="container empty">请先 <Link to="/login">登录</Link>。</div>
  if (!allowed) return <div className="container empty">仅 管理员 可进入管理后台。</div>

  return <div className="container admin-page">
    <header className="panel admin-header"><div><h1>管理后台</h1><p className="muted">管理员 · 全站内容管理。文章删除、用户删除与打卡重置需要验证你自己的密码。</p></div>
      <div className="admin-actions"><Link className="btn ghost" to="/videos">视频链接管理</Link><Link className="btn ghost" to="/study">公共题库管理</Link></div></header>
    <nav className="panel admin-tabs" aria-label="后台分类">{tabs.map(([key, label]) => <button className={`btn ${key === tab ? 'primary' : 'ghost'}`} key={key} onClick={() => changeTab(key)} disabled={busy}>{label}</button>)}</nav>
    {error && <div className="panel admin-error" role="alert">{error}<button className="btn ghost sm" disabled={loading || busy} onClick={() => tab === 'study' ? studyLoad() : load()}>重试</button></div>}
    {message && <p className="admin-message" role="status">{message}</p>}
    {tab !== 'study' && <>
      <form className="admin-toolbar" onSubmit={e => { e.preventDefault(); if (busy) return; setPage(1); setQuery(search) }}>
        {tab !== 'categories' && <><input aria-label="搜索后台数据" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索标题、用户名或内容…" /><button className="btn ghost" disabled={loading}>搜索</button></>}
        <button type="button" className="btn ghost" disabled={loading || busy} onClick={load}>刷新</button>
        {tab === 'posts' && <Link to="/write" className="btn primary">新增文章</Link>}
        {['users', 'categories'].includes(tab) && <button type="button" className="btn primary" disabled={busy} onClick={() => setEdit(tab === 'users' ? { username: '', nickname: '', password: '' } : { name: '' })}>新增{tab === 'users' ? '用户' : '分类'}</button>}
        {tab === 'comments' && <span className="muted">新增评论请进入对应文章。</span>}
      </form>
      {edit && <form className="panel admin-edit" onSubmit={saveEdit}>
        <h2>{edit.id ? '编辑' : '新增'}{tabs.find(t => t[0] === tab)?.[1]}</h2>
        {Object.keys(edit).filter(k => k !== 'id').map(key => <label key={key}>{({ username: '用户名（创建后固定）', nickname: '昵称', password: '初始密码', bio: '简介', avatar_url: '头像地址', name: '分类名称', content: '评论内容' })[key]}
          {['content', 'bio'].includes(key) ? <textarea value={edit[key]} onChange={e => setEdit({ ...edit, [key]: e.target.value })} rows={4} required={key === 'content'} maxLength={key === 'content' ? 2000 : 200} /> :
            <input type={key === 'password' ? 'password' : 'text'} autoComplete={key === 'password' ? 'new-password' : 'off'} value={edit[key]} onChange={e => setEdit({ ...edit, [key]: e.target.value })} required={['username', 'password', 'name'].includes(key)} minLength={key === 'password' ? 6 : undefined} maxLength={key === 'avatar_url' ? 500 : key === 'password' ? 100 : 50} />}
        </label>)}
        <div className="admin-actions"><button className="btn primary" disabled={busy}>{busy ? '保存中…' : '保存'}</button><button type="button" className="btn ghost" disabled={busy} onClick={() => setEdit(null)}>取消</button></div>
      </form>}
      <section className="panel admin-list" aria-busy={loading}>
        {loading ? <div className="empty">加载中…</div> : data.items.length === 0 ? <div className="empty">暂无数据</div> : data.items.map(row => <div className="admin-row" key={row.id}>
          <div className="admin-row-content">
            {tab === 'posts' && <><Link to={`/post/${row.id}`}>{row.title}</Link><small>{row.author.username} · {row.published ? '已发布' : '草稿'}</small></>}
            {tab === 'users' && <><Link to={`/u/${encodeURIComponent(row.username)}`}>{row.nickname || row.username}</Link><small>@{row.username}{row.can_manage ? ' · 超级管理员' : ''}</small></>}
            {tab === 'categories' && <><span>{row.name}</span><small>{row.post_count} 篇文章（含草稿）</small></>}
            {tab === 'comments' && <><p>{row.content}</p><small>{row.author.username} · <Link to={`/post/${row.post_id}`}>文章 #{row.post_id}</Link></small></>}
          </div><div className="admin-actions">
            {tab === 'posts' ? <Link className="btn ghost sm" to={`/edit/${row.id}`}>编辑</Link> : <button className="btn ghost sm" disabled={busy} onClick={() => setEdit(tab === 'users' ? { id: row.id, nickname: row.nickname, bio: row.bio || '', avatar_url: row.avatar_url || '' } : tab === 'categories' ? { id: row.id, name: row.name } : { id: row.id, content: row.content })}>编辑</button>}
            {tab === 'users' && <button className="btn ghost sm" onClick={() => { changeTab('study'); setSelectedUser(String(row.id)) }}>打卡数据</button>}
            {(tab !== 'users' || !row.can_manage) && <button className="btn danger sm" disabled={busy} onClick={() => {
              if (['posts', 'users'].includes(tab)) setDeleting({ kind: tab, id: row.id, title: row.title || row.username })
              else if (window.confirm(tab === 'categories' ? `删除分类“${row.name}”？文章会保留并变为未分类。` : '删除这条评论及其回复？')) mutate(() => tab === 'comments' ? api.deleteComment(row.id) : api.adminRequest(`/categories/${row.id}`, { method: 'DELETE' }))
            }}>删除</button>}
          </div></div>)}
      </section>
      {tab !== 'categories' && <div className="admin-pagination"><button className="btn ghost" disabled={page <= 1 || loading || busy} onClick={() => setPage(p => p - 1)}>上一页</button><span>第 {page} 页 · 共 {data.total} 条</span><button className="btn ghost" disabled={page * 20 >= data.total || loading || busy} onClick={() => setPage(p => p + 1)}>下一页</button></div>}
    </>}
    {tab === 'study' && <>
      <section className="panel admin-edit">
        <h2>选择用户</h2><p className="muted">读取今日任务时会为该用户生成当天任务快照；历史记录保持原样。</p>
        <form className="admin-toolbar" onSubmit={async e => { e.preventDefault(); setError(''); try { const r = await api.adminRequest(`/users?page_size=50&search=${encodeURIComponent(userSearch)}`); setUsers(r.items) } catch (e) { setError(e.message) } }}>
          <input aria-label="查找打卡用户" value={userSearch} onChange={e => setUserSearch(e.target.value)} placeholder="查找用户名…" /><button className="btn ghost">查找用户</button>
        </form>
        <div className="admin-toolbar"><select aria-label="选择打卡用户" value={selectedUser} disabled={busy} onChange={e => { studyVersion.current++; setSelectedUser(e.target.value); setStudy(null); setTaskEdit(null); setLoading(false) }}><option value="">请选择用户</option>{users.map(u => <option key={u.id} value={u.id}>{u.username} · {u.nickname}</option>)}</select>
          <input type="month" aria-label="历史记录月份" value={month} disabled={loading || busy} onChange={e => setMonth(e.target.value)} required />
          <button className="btn primary" disabled={!selectedUser || loading || busy || !month} onClick={() => studyLoad()}>读取打卡数据</button></div>
      </section>
      {loading && <div className="panel empty">加载打卡数据…</div>}
      {study && <>
        <section className="panel admin-edit"><h2>今日任务 · {study.day.date} · {study.day.done}/{study.day.total}</h2>
          {study.day.tasks.map(task => <div className="admin-row" key={task.key}><div className="admin-row-content"><span>{task.done ? '✅' : '⬜'} {task.title}</span><small>{labels[task.kind]} · {task.weak ? '待加强' : '正常'}{task.note ? ` · ${task.note}` : ''}</small></div><button className="btn ghost sm" onClick={() => setTaskEdit({ ...task })} disabled={busy}>修改状态/备注</button></div>)}
          {taskEdit && <form className="admin-task-edit" onSubmit={e => { e.preventDefault(); mutate(async () => { await api.adminRequest(`/users/${study.userId}/study/tasks/${encodeURIComponent(taskEdit.key)}`, { method: 'PUT', body: { done: taskEdit.done, weak: taskEdit.weak, note: taskEdit.note || '' } }); await studyLoad(study.userId) }) }}><h3>{taskEdit.title}</h3><label><input type="checkbox" checked={taskEdit.done} onChange={e => setTaskEdit({ ...taskEdit, done: e.target.checked })} /> 已完成</label><label><input type="checkbox" checked={taskEdit.weak} onChange={e => setTaskEdit({ ...taskEdit, weak: e.target.checked })} /> 待加强</label><textarea aria-label="打卡备注" rows={3} maxLength={2000} value={taskEdit.note || ''} onChange={e => setTaskEdit({ ...taskEdit, note: e.target.value })} /><div className="admin-actions"><button className="btn primary" disabled={busy}>保存任务</button><button className="btn ghost" type="button" onClick={() => setTaskEdit(null)}>取消</button></div></form>}
        </section>
        <section className="panel admin-edit"><h2>轮次进度</h2>{study.progress.map(round => <div className="admin-row" key={round.id}><span>{labels[round.kind]} · 第 {round.number} 轮 · {round.done}/{round.total} · {round.finished ? '已完成' : '进行中'}</span>{round.finished && !study.progress.some(r => r.kind === round.kind && r.number > round.number) && <button className="btn ghost sm" disabled={busy} onClick={() => mutate(async () => { await api.adminRequest(`/users/${study.userId}/study/rounds/${round.kind}/next`, { method: 'POST', body: { mode: 'all' } }); await studyLoad(study.userId) })}>开启下一轮</button>}</div>)}</section>
        <section className="panel admin-edit"><h2>历史快照 · {study.month}</h2><p className="muted">历史任务只读，题库修改不会回写过去的记录。</p>{study.history.length === 0 ? <p>该月暂无记录。</p> : study.history.map(day => <details key={day.date}><summary>{day.date} · 完成 {day.done}/{day.total}</summary>{day.tasks.map(t => <p key={t.key}>{t.done ? '✅' : '⬜'} {t.title}{t.note ? ` · ${t.note}` : ''}</p>)}</details>)}
          <button className="btn danger" disabled={busy} onClick={() => setDeleting({ kind: 'study', id: study.userId, title: users.find(u => String(u.id) === String(study.userId))?.username || `用户 #${study.userId}` })}>重置该用户全部打卡数据</button></section>
      </>}
    </>}
    {deleting && <PasswordConfirm title={deleting.kind === 'study' ? '确认重置打卡数据' : deleting.kind === 'users' ? '确认删除用户' : '确认删除文章'} description={deleting.kind === 'users' ? `删除用户 ${deleting.title} 将同时删除其文章、评论、互动和全部打卡数据。此操作不可撤销，请输入 管理员 自己的密码。` : deleting.kind === 'study' ? `重置 ${deleting.title} 的全部历史打卡和轮次进度，公共题库保留。请输入 管理员 自己的密码。` : `删除《${deleting.title}》及关联评论、点赞、收藏。请输入 管理员 自己的密码。`} onConfirm={remove} onCancel={() => setDeleting(null)} />}
  </div>
}
