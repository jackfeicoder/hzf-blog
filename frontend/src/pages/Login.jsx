import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await login(username.trim(), password)
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
        <h2>登录 CodeBlog</h2>
        <p className="muted">欢迎回来，继续创作与交流</p>
        {err && <div className="alert">{err}</div>}
        <label>
          用户名
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </label>
        <label>
          密码
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <button className="btn primary block" disabled={busy}>
          {busy ? '登录中...' : '登录'}
        </button>
        <p className="auth-foot">
          还没有账号？ <Link to="/register">立即注册</Link>
        </p>
      </form>
    </div>
  )
}
