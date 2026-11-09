import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { pageAccess } from '../navigation'

export default function GuestAccess({ children }) {
  const { user, loading } = useAuth()
  const { pathname } = useLocation()
  const access = pageAccess(pathname, user, loading)
  if (access === 'pending') return <div className="container empty">正在确认登录状态…</div>
  if (access === 'denied') return <Navigate to="/welcome" replace />
  return children
}
