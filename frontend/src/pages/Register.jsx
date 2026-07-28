import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'

export default function Register() {
  const { register } = useAuth()
  const nav = useNavigate()
  const [username, setUsername] = useState('')
  const [nickname, setNickname] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await register(username.trim(), password, nickname.trim())
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
        <p className="muted">加入社区，分享你的技术见解</p>
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
