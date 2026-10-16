import { Navigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { adminAccess } from '../navigation'

export default function AdminOnly({ children }) {
  const { user, loading } = useAuth()
  const access = adminAccess(user, loading)
  if (access === 'pending') return <div className="container empty">正在验证登录状态…</div>
  if (access === 'denied') return <Navigate to="/" replace />
  return children
}
