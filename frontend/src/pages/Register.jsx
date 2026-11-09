import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'

export default function Register() {
  const { register } = useAuth()
  const nav = useNavigate()
  const [username, setUsername] = useState('')
  const [nickname, setNickname] = useState('')
  const [password, setPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await register(username.trim(), password, nickname.trim(), inviteCode.trim().toUpperCase())
      nav('/')
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <form className="panel auth-card" onSubmit={onSubmit}>
        <h2>注册 CodeBlog</h2>
        <p className="muted">注册需使用管理员提供的6位邀请码，每个邀请码仅可使用一次。已有账号可直接登录。</p>
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
          昵称（可选）
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
        <label>
          邀请码
          <input value={inviteCode} onChange={e => setInviteCode(e.target.value.toUpperCase())}
            minLength={6} maxLength={6} pattern="[A-Za-z0-9]{6}" autoComplete="off"
            placeholder="输入管理员提供的6位邀请码" required />
        </label>
        <button className="btn primary block" disabled={busy}>
          {busy ? '注册中...' : '注册'}
        </button>
        <p className="auth-foot">
          已有账号？ <Link to="/login">去登录</Link>
        </p>
      </form>
    </div>
  )
}
