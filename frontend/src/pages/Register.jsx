import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../api'

export default function Register() {
  const { register, user, loading } = useAuth()
  const nav = useNavigate()
  const [username, setUsername] = useState('')
  const [nickname, setNickname] = useState('')
  const [password, setPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [policy, setPolicy] = useState(null)
  const [policyError, setPolicyError] = useState('')

  const loadPolicy = async () => {
    try { const result = await api.registrationSettings(); setPolicy(result); setPolicyError('') }
    catch { setPolicyError('注册设置读取失败，请重试'); setPolicy(null) }
  }
  useEffect(() => { loadPolicy() }, [])

  const onSubmit = async (e) => {
    e.preventDefault()
    if (busy || policy === null) return
    setBusy(true)
    setErr('')
    try {
      await register(username.trim(), password, nickname.trim(), policy.invite_required ? inviteCode.trim().toUpperCase() : '')
      nav('/')
    } catch (e) {
      setErr(e.message)
      await loadPolicy()
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div className="container empty">正在确认登录状态…</div>
  if (user) return <div className="container panel auth-card"><h2>当前已登录</h2>
    <p>当前账号：{user.nickname || user.username}（用户名：{user.username}）。注册新账号请先退出当前账号。</p>
    <Link className="btn primary" to="/">返回首页</Link></div>

  return (
    <div className="auth-page">
      <form className="panel auth-card" onSubmit={onSubmit}>
        <h2>注册 CodeBlog</h2>
        <p className="muted">{policy === null ? '正在读取注册设置…' : policy.invite_required ? '注册需使用管理员提供的6位邀请码，每个邀请码仅可使用一次。已有账号可直接登录。' : '当前开放注册，填写账号信息即可加入。已有账号可直接登录。'}</p>
        {policyError && <div className="alert" role="alert">{policyError} <button type="button" className="btn ghost sm" onClick={loadPolicy}>重新读取</button></div>}
        {err && <div className="alert">{err}</div>}
        <label>
          用户名
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            minLength={2}
            required
            autoFocus
          />
        </label>
        <label>
          昵称（可选，可重复）
          <input value={nickname} onChange={(e) => setNickname(e.target.value)} />
        </label>
        <label>
          密码（至少 6 位）
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={6}
            required
          />
        </label>
        {policy?.invite_required && <label>
          邀请码
          <input value={inviteCode} onChange={e => setInviteCode(e.target.value.toUpperCase())}
            minLength={6} maxLength={6} pattern="[A-Za-z0-9]{6}" autoComplete="off"
            placeholder="输入管理员提供的6位邀请码" required />
        </label>}
        <button className="btn primary block" disabled={busy || policy === null}>
          {busy ? '注册中...' : '注册'}
        </button>
        <p className="auth-foot">
          已有账号？ <Link to="/login">去登录</Link>
        </p>
      </form>
    </div>
  )
}
