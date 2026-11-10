import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../api'
import { pageAccess } from '../navigation'

export default function VisitTracker() {
  const { pathname } = useLocation()
  const { user, loading } = useAuth()
  useEffect(() => {
    if (loading || pageAccess(pathname, user, false) !== 'allowed') return
    // Best effort: never delay page rendering, playback or navigation.
    api.trackVisit(pathname).catch(() => {})
  }, [pathname, user?.id, loading])
  return null
}
