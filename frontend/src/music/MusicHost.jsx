import { lazy, Suspense, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
const PlayerEngine = lazy(() => import('./PlayerEngine'))
export default function MusicHost() {
  const { pathname } = useLocation()
  const [activated, setActivated] = useState(pathname === '/music')
  useEffect(() => { if (pathname === '/music') setActivated(true) }, [pathname])
  return activated ? <Suspense fallback={null}><PlayerEngine /></Suspense> : null
}
