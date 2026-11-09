import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

const statusText = { available: '可使用', used: '已使用', revoked: '已作废' }

export default function InviteManager() {
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ items: [], total: 0 })
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [freshCode, setFreshCode] = useState('')
  const [settings, setSettings] = useState(null)
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [invites, policy] = await Promise.all([api.invitations(page), api.registrationSettings()])
      setData(invites); setSettings(policy); setError('')
    }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [page])
  useEffect(() => { load() }, [load])
  const mutate = async fn => {
    if (busy) return
    setBusy(true); setError(''); setMessage('')
    try { await fn(); await load() }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  const copy = async code => {
    try { await navigator.clipboard.writeText(code); setMessage('邀请码已复制') }
    catch { setMessage('请长按或选中邀请码手动复制') }
  }
  return <section className="panel admin-edit">
    <h2>注册邀请码</h2>
    <div className="admin-row">
      <div className="admin-row-content"><strong>开启邀请注册</strong>
        <small>{settings === null ? '正在读取设置…' : settings.invite_required ? '已开启：新用户必须填写邀请码' : '已关闭：新用户可以直接注册'}。已有用户登录不受影响。</small></div>
      <button type="button" role="switch" aria-label="开启邀请注册" aria-checked={settings?.invite_required ?? true}
        className={`btn ${settings?.invite_required ? 'primary' : 'ghost'}`} disabled={busy || loading || settings === null}
        onClick={() => {
          const next = !settings.invite_required
          if (window.confirm(next ? '开启邀请注册？之后的新注册必须填写邀请码。' : '关闭邀请注册？所有访客都可以直接注册账号。')) mutate(async () => {
            const saved = await api.saveRegistrationSettings(next); setSettings(saved)
            setMessage(saved.invite_required ? '已开启邀请注册' : '已开放注册')
          })
        }}>{settings === null ? '读取中…' : settings.invite_required ? '已开启' : '已关闭'}</button>
    </div>
    <h3>邀请码生成与管理</h3>
    <p className="muted">仅管理员可生成和管理。6位随机字母数字，每码仅可注册一个账号；已有用户登录不受影响。</p>
    {error && <p className="admin-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <div className="admin-actions">
      <button className="btn primary" disabled={busy || loading} onClick={() => mutate(async () => {
        const invite = await api.createInvitation(); setFreshCode(invite.code)
      })}>{busy ? '处理中…' : '生成邀请码'}</button>
      <button className="btn ghost" disabled={busy || loading} onClick={load}>刷新</button>
    </div>
    {freshCode && <p>刚生成：<strong><code>{freshCode}</code></strong> <button className="btn ghost sm" onClick={() => copy(freshCode)}>复制</button></p>}
    <div className="admin-list" aria-busy={loading}>
      {loading ? <p>加载中…</p> : !data.items.length ? <p className="muted">暂无邀请码，点击上方按钮生成。</p> : data.items.map(row => <div className="admin-row" key={row.id}>
        <div className="admin-row-content"><strong><code>{row.code}</code></strong>
          <small>{statusText[row.status]}{row.used_by ? ` · 注册用户：${row.used_by}` : ''} · {new Date(`${row.created_at}Z`).toLocaleString()}</small></div>
        {row.status === 'available' && <div className="admin-actions">
          <button className="btn ghost sm" onClick={() => copy(row.code)}>复制</button>
          <button className="btn danger sm" disabled={busy} onClick={() => {
            if (window.confirm(`作废邀请码 ${row.code}？作废后将失效。`)) mutate(async () => {
              await api.revokeInvitation(row.id); if (freshCode === row.code) setFreshCode('')
            })
          }}>作废</button>
        </div>}
      </div>)}
    </div>
    <div className="admin-pagination">
      <button className="btn ghost" disabled={page <= 1 || busy || loading} onClick={() => setPage(p => p - 1)}>上一页</button>
      <span>第{page}页 · 共{data.total}个邀请码</span>
      <button className="btn ghost" disabled={page * 20 >= data.total || busy || loading} onClick={() => setPage(p => p + 1)}>下一页</button>
    </div>
  </section>
}
