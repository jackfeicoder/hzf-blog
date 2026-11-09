import { lazy, Suspense, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../AuthContext'
const PlayerEngine = lazy(() => import('./PlayerEngine'))
export default function MusicHost() {
  const { user, loading } = useAuth()
  const { pathname } = useLocation()
  const [activated, setActivated] = useState(false)
  useEffect(() => {
    if (user && pathname === '/music') setActivated(true)
    if (!loading && !user) setActivated(false)
  }, [pathname, user?.id, loading])
  return !loading && user && activated ? <Suspense fallback={null}><PlayerEngine /></Suspense> : null
}
