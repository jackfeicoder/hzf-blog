import { useEffect } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { getToken } from '../api'
import { shouldShowWelcome, welcomeHistory } from './policy'

export default function WelcomeGate({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  useEffect(() => { if (user) welcomeHistory.markSeen() }, [user?.id])
  const hasToken = !!getToken(), seen = welcomeHistory.hasSeen()
  if (loading && !hasToken && !seen) return <div className="container empty">正在打开博客…</div>
  if (shouldShowWelcome({ ...location, user, loading, hasToken, seen })) {
    return <Navigate to="/welcome" replace />
  }
  // A saved session being checked, or a slow network, must not flash a welcome
  // page for existing users. Ordinary content stays usable during auth loading.
  return children
}
