import { useState } from 'react'
import { api } from '../api'

export default function PasswordChange({ onSuccess, onClose }) {
  const [current, setCurrent] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async event => {
    event.preventDefault()
    if (busy) return
    setError('')
    if (password.length < 8 || new TextEncoder().encode(password).length > 72) {
      setError('新密码至少 8 个字符，UTF-8 长度不超过 72 字节'); return
    }
    if (password !== confirm) { setError('两次输入的新密码不一致'); return }
    if (password === current) { setError('新密码应与当前密码不同'); return }
    setBusy(true)
    try {
      await api.changePassword({ current_password: current, new_password: password, confirm_password: confirm })
      setCurrent(''); setPassword(''); setConfirm('')
      onSuccess()
    } catch (err) { setError(err.message || '修改失败，请稍后重试') }
    finally { setBusy(false) }
  }
  return <section className="panel password-panel" aria-labelledby="password-title">
    <h2 id="password-title">修改密码</h2>
    <p className="muted">验证当前密码后设置新密码。成功后所有设备需要重新登录。</p>
    <form onSubmit={submit}>
      {error && <div className="alert" role="alert">{error}</div>}
      <label htmlFor="current-password">当前密码</label>
      <input id="current-password" type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} maxLength={100} required disabled={busy} autoFocus />
      <label htmlFor="new-password">新密码</label>
      <input id="new-password" type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} minLength={8} maxLength={72} required disabled={busy} aria-describedby="password-hint" />
      <small id="password-hint" className="muted">至少 8 个字符，建议使用长密码并混合字母、数字和符号。</small>
      <label htmlFor="confirm-password">确认新密码</label>
      <input id="confirm-password" type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} minLength={8} maxLength={72} required disabled={busy} />
      <div className="password-buttons"><button className="btn primary" disabled={busy}>{busy ? '修改中…' : '确认修改'}</button><button type="button" className="btn ghost" onClick={onClose} disabled={busy}>取消</button></div>
    </form>
  </section>
}
