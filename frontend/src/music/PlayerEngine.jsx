import { useEffect, useRef } from 'react'
import { useAuth } from '../AuthContext'
import { MusicController } from './controller'
import PlayerBar from './PlayerBar'
import './music.css'

export default function PlayerEngine() {
  const audio = useRef(null), controller = useRef(null)
  const { user, loading } = useAuth()
  useEffect(() => { controller.current = new MusicController(audio.current); return () => controller.current?.destroy() }, [])
  useEffect(() => { if (!loading) controller.current?.actor(user) }, [user?.id, user?.username, loading])
  return <><audio ref={audio} preload="metadata" /><PlayerBar /></>
}
