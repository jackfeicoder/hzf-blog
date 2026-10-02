import { useEffect, useRef, useState } from 'react'
import './password-confirm.css'

// Password stays only in this mounted form, never persistent storage.
export default function PasswordConfirm({ title = '确认删除文章', description, onConfirm, onCancel }) {
  const dialog = useRef(null)
  const input = useRef(null)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const el = dialog.current
    el.showModal()
    input.current.focus()
    return () => el.close()
  }, [])
  useEffect(() => { if (error && !busy) input.current?.focus() }, [error, busy])
  const submit = async (event) => {
    event.preventDefault()
    if (!password || busy) return
    setBusy(true); setError('')
    try { await onConfirm(password) }
    catch (e) { setPassword(''); setError(e.message); setBusy(false) }
  }
  return <dialog ref={dialog} className="password-confirm" aria-labelledby="password-confirm-title"
    onCancel={e => { e.preventDefault(); if (!busy) onCancel() }}>
    <form onSubmit={submit}>
      <h2 id="password-confirm-title">{title}</h2>
      <p>{description || '删除后文章及关联评论、点赞、收藏将被清理，请确认。'}</p>
      <label htmlFor="delete-password">输入你当前账户的登录密码</label>
      <input ref={input} id="delete-password" name="password" type="password" autoComplete="current-password"
        value={password} onChange={e => setPassword(e.target.value)} required maxLength={100} disabled={busy} />
      {error && <p className="password-error" role="alert">{error}</p>}
      <div className="password-actions">
        <button type="button" className="btn ghost" disabled={busy} onClick={onCancel}>取消</button>
        <button className="btn danger" disabled={!password || busy}>{busy ? '正在处理…' : '验证并确认删除'}</button>
      </div>
    </form>
  </dialog>
}
