import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../api'
import './study.css'

const labels = { java: 'Java八股', hot100: 'Hot100', project: '项目学习' }
const blank = { kind: 'java', title: '', answer: '', source_url: '', position: 0, active: true }
const beijingMonth = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit' }).format(new Date())

function Source({ url }) {
  return url ? <a href={url} target="_blank" rel="noopener noreferrer">阅读对应文章 ↗</a> : null
}

function Task({ task, disabled, save }) {
  const [note, setNote] = useState(task.note || '')
  useEffect(() => setNote(task.note || ''), [task.note])
  return <div className={`study-task ${task.done ? 'is-done' : ''}`}>
    <label className="study-check"><input type="checkbox" checked={task.done} disabled={disabled} onChange={e => save(task, { done: e.target.checked })} /><span>{task.title}</span></label>
    <div className="study-task-meta"><Source url={task.source_url} />{task.round && <span>第 {task.round} 轮</span>}<label><input type="checkbox" checked={task.weak} disabled={disabled} onChange={e => save(task, { weak: e.target.checked })} /> 重点复习</label></div>
    {task.answer && <details><summary>学习内容 / 参考答案</summary><div className="study-answer">{task.answer}</div></details>}
    <input aria-label={`${task.title}学习笔记`} className="study-note" maxLength={2000} placeholder="一句话记录今天的收获（离开输入框保存）" value={note} disabled={disabled} onChange={e => setNote(e.target.value)} onBlur={() => { if (note !== task.note) save(task, { note }) }} />
  </div>
}

export default function Study() {
  const { user, loading } = useAuth()
  const [tab, setTab] = useState('today')
  const [day, setDay] = useState(null)
  const [rounds, setRounds] = useState([])
  const [history, setHistory] = useState([])
  const [month, setMonth] = useState(beijingMonth)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [bank, setBank] = useState([])
  const [edit, setEdit] = useState({ ...blank })
  const [filter, setFilter] = useState('java')
  const [postId, setPostId] = useState('')
  const [preview, setPreview] = useState(null)
  const [selected, setSelected] = useState([])
  const latestDay = useRef(null)
  const saves = useRef(Promise.resolve())
  const activeUserId = useRef(user?.id)
  useEffect(() => { latestDay.current = day }, [day])

  async function run(action) {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function reload() {
    const d = await api.studyToday()
    latestDay.current = d
    setDay(d)
    setRounds(await api.studyProgress())
  }
  useEffect(() => {
    activeUserId.current = user?.id
    latestDay.current = null
    setDay(null); setRounds([]); setHistory([]); setBank([]); setPreview(null); setEdit({ ...blank })
    if (!user) return
    let live = true
    setError('')
    // The day may create rounds: show tasks immediately, then fetch progress.
    api.studyToday().then(async d => {
      if (!live) return
      latestDay.current = d
      setDay(d)
      const r = await api.studyProgress()
      if (live) setRounds(r)
    }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [user?.id])
  useEffect(() => {
    if (!user || tab !== 'history') return
    let live = true
    api.studyHistory(month).then(data => { if (live) setHistory(data) }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [user?.id, tab, month])
  useEffect(() => {
    if (!user?.is_admin || tab !== 'bank') return
    let live = true
    api.studyBank().then(data => { if (live) setBank(data) }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [user?.id, tab])

  const saveTask = (task, changes) => {
    const ownerId = user.id
    // Blur and checkbox events can arrive together. Serialize and merge into
    // the latest server result so a note save never undoes a fresh checkmark.
    saves.current = saves.current.then(() => run(async () => {
      if (activeUserId.current !== ownerId) return
      const current = latestDay.current?.tasks.find(t => t.key === task.key) || task
      const saved = await api.studyTask(task.key, { done: current.done, weak: current.weak, note: current.note, ...changes })
      if (activeUserId.current !== ownerId) return
      latestDay.current = saved
      setDay(saved)
      setRounds(await api.studyProgress())
      setNotice('已保存')
    }))
  }
  const nextRound = (kind, mode) => {
    if (!window.confirm(`开始${labels[kind]}下一轮${mode === 'weak' ? '重点' : '全部'}复习？今天的任务保持原样，新轮次明天开始。`)) return
    run(async () => { const result = await api.studyNextRound(kind, mode); await reload(); setNotice(result.message) })
  }

  if (loading) return <main className="study-page">正在确认登录状态…</main>
  if (!user) return <main className="study-page"><section className="study-panel"><h1>学习打卡</h1><p>每天 5 道 Java八股、2 道 Hot100 和一项项目学习。你的任务和复习记录独立保存。</p><Link className="btn btn-primary" to="/login">登录后开始学习</Link></section></main>

  return <main className="study-page">
    <section className="study-panel study-hero"><div><h1>学习打卡</h1><p>每天积累一点，下一轮再巩固一点。</p></div><div className="study-summary"><strong>{day?.done ?? 0} / {day?.total ?? 0}</strong><span>{day?.date || '加载中'} · 北京时间</span></div></section>
    <nav className="study-tabs" aria-label="学习打卡栏目">{[['today', '今日任务'], ['progress', '学习进度'], ['history', '打卡日历'], ...(user.is_admin ? [['bank', '题库维护']] : [])].map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {error && <div className="study-error" role="alert">{error}<button disabled={busy} onClick={() => run(reload)}>刷新任务</button></div>}
    <div className="study-status" role="status">{busy ? '正在保存…' : notice}</div>
    {tab === 'today' && <><div className="study-form-row"><p className="study-help">勾选即保存，可以取消。未完成题目优先延续到次日；当天题目固定，跨日后请刷新。</p><button disabled={busy} onClick={() => run(reload)}>刷新今日任务</button></div><div className="study-columns">{Object.entries(labels).map(([kind, label]) => {
      const tasks = day?.tasks.filter(t => t.kind === kind) || []
      return <section className="study-panel" key={kind}><h2>{label}<small>{tasks.filter(t => t.done).length} / {tasks.length}</small></h2>{tasks.map(task => <Task key={`${day.date}-${task.key}`} task={task} disabled={rounds.some(r => r.kind === task.kind && r.number > (task.round || Infinity))} save={saveTask} />)}{day && !tasks.length && <p>本轮任务已完成。到「学习进度」开始下一轮；新题目将在下一轮纳入。</p>}{kind === 'project' && <p className="study-help">默认顺序：HelloAgent → paicli → RAG。管理员可拆分更细的学习里程碑。</p>}</section>
    })}</div></>}
    {tab === 'progress' && <section className="study-panel"><h2>我的复习轮次</h2><p className="study-help">Java、Hot100、项目分别记录进度。题库更新从次日生效，已完成轮次保留历史。</p>{Object.entries(labels).map(([kind, label]) => {
      const list = rounds.filter(r => r.kind === kind)
      return <div className="study-round-group" key={kind}><h3>{label}</h3>{list.map((r, index) => <div className="study-round" key={r.id}><span>第 {r.number} 轮 · {r.finished ? '已完成' : '进行中'}</span><progress value={r.done} max={r.total || 1} /><span>{r.done} / {r.total} · 重点 {r.weak}</span>{index === 0 && r.finished && <div><button disabled={busy} onClick={() => nextRound(kind, 'all')}>下一轮全部复习</button><button disabled={busy || !r.weak} onClick={() => nextRound(kind, 'weak')}>只复习重点</button></div>}</div>)}{!list.length && <p>暂无轮次</p>}</div>
    })}</section>}
    {tab === 'history' && <section className="study-panel"><h2>打卡日历 <input aria-label="选择月份" type="month" value={month} onChange={e => setMonth(e.target.value || beijingMonth())} /></h2><p className="study-help">只展示自己的记录。全部完成、部分完成分别标记，历史任务保留原内容。</p><div className="study-calendar">{['一', '二', '三', '四', '五', '六', '日'].map(d => <span className="study-weekday" key={d}>周{d}</span>)}{Array.from({ length: (new Date(Number(month.slice(0, 4)), Number(month.slice(5)) - 1, 1).getDay() + 6) % 7 }, (_, i) => <span aria-hidden="true" key={`blank-${i}`} />)}{Array.from({ length: new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0).getDate() }, (_, i) => {
      const date = `${month}-${String(i + 1).padStart(2, '0')}`
      const d = history.find(h => h.date === date)
      return <a key={date} href={d ? `#study-day-${date}` : undefined} className={d?.total && d.done === d.total ? 'complete' : d?.done ? 'partial' : ''} aria-label={`${date} ${d ? `${d.done}/${d.total}` : '未打卡'}`}><strong>{i + 1}</strong><small>{d ? `${d.done}/${d.total}` : '—'}</small></a>
    })}</div>{history.map(d => <details id={`study-day-${d.date}`} key={d.date} className="study-history"><summary>{d.date} · {d.done} / {d.total} {d.total && d.done === d.total ? '全部完成' : '部分完成'}</summary>{d.tasks.map(t => <div key={t.key}><p>{t.done ? '☑' : '☐'} {labels[t.kind]} · {t.title}</p>{t.note && <p className="study-help">{t.note}</p>}<Source url={t.source_url} /></div>)}</details>)}</section>}
    {tab === 'bank' && user.is_admin && <>
      <section className="study-panel"><h2>公共题库维护</h2><p className="study-help">编辑保留原编号；停用代替删除。数字越小越先学习。当天任务和历史快照保持原样。项目可拆分为多个阶段任务。</p><div className="study-form-row"><label>题库<select value={filter} onChange={e => { setFilter(e.target.value); setEdit({ ...blank, kind: e.target.value }); setPreview(null); setPostId('') }}>{Object.entries(labels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><button disabled={busy} onClick={() => setEdit({ ...blank, kind: filter, position: bank.filter(i => i.kind === filter).length })}>新增题目 / 里程碑</button></div>
      <form className="study-form" onSubmit={e => { e.preventDefault(); run(async () => { await api.studySaveItem(edit); setBank(await api.studyBank()); setEdit({ ...blank, kind: filter }); setNotice('题库已保存，次日任务使用新内容') }) }}>
        <h3>{edit.id ? `编辑 #${edit.id}` : '新增'}</h3><label>标题<input required maxLength={500} value={edit.title} onChange={e => setEdit({ ...edit, title: e.target.value })} /></label><label>答案 / 学习目标<textarea rows={5} maxLength={50000} value={edit.answer} onChange={e => setEdit({ ...edit, answer: e.target.value })} /></label><div className="study-form-row"><label>对应文章链接<input placeholder="/post/5 或 https://…" value={edit.source_url} onChange={e => setEdit({ ...edit, source_url: e.target.value })} /></label><label>排序<input type="number" min="0" max="1000000" value={edit.position} onChange={e => setEdit({ ...edit, position: Number(e.target.value) })} /></label><label><input type="checkbox" checked={edit.active} onChange={e => setEdit({ ...edit, active: e.target.checked })} />启用</label></div><button className="btn btn-primary" disabled={busy}>保存题目</button>
      </form><div className="study-bank-list">{bank.filter(i => i.kind === filter).map(item => <div key={item.id}><span>#{item.id} · 排序 {item.position} · {item.active ? '启用' : '已停用'}<br />{item.title}</span><button disabled={busy} onClick={() => { setEdit({ ...item }); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>编辑</button></div>)}{!bank.some(i => i.kind === filter) && <p>题库尚未导入，可手动新增或从下方文章预览。</p>}</div></section>
      {filter !== 'project' && <section className="study-panel"><h2>从文章预览导入</h2><p className="study-help">默认 Java 来源《Java八股》；Hot100 来源文章 5。识别 Markdown 编号条目，先检查并勾选真正的题目，再确认导入。答案内的编号也可能被识别，建议人工核对。</p><div className="study-form-row"><input aria-label="文章编号" type="number" min="1" placeholder={filter === 'hot100' ? '文章编号：5' : '输入 Java八股 的文章编号'} value={postId} onChange={e => setPostId(e.target.value)} /><button disabled={busy} onClick={() => run(async () => {
        let id = Number(postId || (filter === 'hot100' ? 5 : 0))
        if (!id && filter === 'java') { const posts = await api.listPosts({ search: 'Java八股', page_size: 50 }); const found = posts.items?.find(p => p.title === 'Java八股'); if (found) id = found.id }
        if (!id) throw new Error('请填写文章编号')
        const data = await api.studyPreview(id, filter); setPreview(data); setSelected([])
      })}>预览识别结果</button></div>{preview && <><h3>{preview.title} · {preview.items.length} 个候选条目</h3><button onClick={() => setSelected(preview.items.map((_, i) => i))}>全选</button> <button onClick={() => setSelected([])}>清空选择</button><div className="study-import-list">{preview.items.map((item, i) => <details key={i}><summary><label onClick={e => e.stopPropagation()}><input type="checkbox" checked={selected.includes(i)} onChange={e => setSelected(e.target.checked ? [...selected, i] : selected.filter(n => n !== i))} />{item.title}</label></summary><div className="study-answer">{item.answer || '无答案，可导入后补充'}</div></details>)}</div><button className="btn btn-primary" disabled={busy || !selected.length} onClick={() => run(async () => { const result = await api.studyImport(selected.map(i => preview.items[i])); setBank(await api.studyBank()); setPreview(null); setNotice(`导入 ${result.added} 题，跳过 ${result.skipped} 个重复题。次日起纳入任务。`) })}>确认导入 {selected.length} 个条目</button>{!preview.items.length && <p>没有识别到编号条目，请手动添加，文章内容保留为阅读来源。</p>}</>}</section>}
    </>}
  </main>
}
