import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../AuthContext'
import { api, getToken } from '../api'
import { appearanceKey, glassOpacity, normalizeAppearance, readAppearance, writeAppearance } from './settings'

const Context = createContext(null)
const key = appearanceKey()
const storage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) }

export default function AppearanceProvider({ children }) {
  const { user } = useAuth()
  const canEdit = user?.can_manage === true
  const [published, setPublished] = useState(() => readAppearance(key, storage))
  const [draft, setDraft] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [systemReduce, setSystemReduce] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false)
  const session = useRef({ user, token: getToken() })
  session.current = { user, token: getToken() }
  const draftRef = useRef(draft)
  draftRef.current = draft
  const saving = useRef(false), mounted = useRef(false), readBusy = useRef(false), revision = useRef(0)
  const settings = canEdit && draft?.owner === user.id ? draft.settings : published
  const dark = settings.theme === 'dark'
  const reduced = !settings.motion || systemReduce

  const acceptPublished = useCallback(value => {
    const next = normalizeAppearance(value)
    writeAppearance(key, next, storage)
    setPublished(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next)
  }, [])

  const refresh = useCallback(async () => {
    if (readBusy.current || saving.current) return
    readBusy.current = true
    const version = revision.current
    try {
      const value = await api.getAppearance()
      if (!mounted.current || revision.current !== version) return
      acceptPublished(value)
      if (!draftRef.current) { setStatus('saved'); setError('') }
    } catch {
      if (mounted.current && revision.current === version && !draftRef.current) setStatus('offline')
    } finally { readBusy.current = false }
  }, [acceptPublished])

  useEffect(() => {
    mounted.current = true
    refresh()
    const wake = () => { if (document.visibilityState !== 'hidden') refresh() }
    const sync = event => {
      if (event.key === key || event.key === null) {
        revision.current += 1
        setPublished(readAppearance(key, storage))
      }
    }
    // One small background read per 30 seconds, only while visible. It does not
    // block page rendering, images, clicks or route changes.
    const timer = setInterval(wake, 30_000)
    window.addEventListener('focus', wake)
    window.addEventListener('online', wake)
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('storage', sync)
    return () => {
      mounted.current = false
      clearInterval(timer)
      window.removeEventListener('focus', wake)
      window.removeEventListener('online', wake)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('storage', sync)
    }
  }, [refresh])

  useEffect(() => {
    setDraft(null); draftRef.current = null
    setError('')
    refresh()
  }, [user?.id, refresh])

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const listener = event => setSystemReduce(event.matches)
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [])

  useLayoutEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', dark)
    root.dataset.palette = settings.palette
    root.dataset.motion = reduced ? 'off' : 'on'
    root.dataset.cursor = settings.cursor
    root.dataset.background = settings.background
    root.style.setProperty('--glass-opacity', String(glassOpacity(settings)))
  }, [dark, reduced, settings.palette, settings.cursor, settings.background, settings.glass_transparency])

  const update = useCallback(patch => {
    if (!canEdit || saving.current) return
    const previous = draftRef.current?.owner === user.id ? draftRef.current.settings : published
    const next = { owner: user.id, settings: normalizeAppearance({ ...previous, ...patch }) }
    draftRef.current = next
    setDraft(next); setStatus('draft'); setError('')
  }, [canEdit, user?.id, published])

  const discard = useCallback(() => {
    if (saving.current) return
    draftRef.current = null
    setDraft(null); setStatus('saved'); setError('')
  }, [])

  const publish = useCallback(async () => {
    if (!canEdit || saving.current || draftRef.current?.owner !== user.id) return
    const current = draftRef.current, token = getToken(), owner = user.id
    saving.current = true
    revision.current += 1
    setStatus('saving'); setError('')
    try {
      const value = await api.saveAppearance(current.settings)
      if (!mounted.current) return
      acceptPublished(value)
      setStatus('saved')
      if (session.current.user?.id === owner && session.current.token === token) {
        draftRef.current = null
        setDraft(null); setStatus('saved')
      }
    } catch (err) {
      if (mounted.current && session.current.user?.id === owner && session.current.token === token) {
        setStatus('error'); setError(err.message || '全站样式保存失败，请重试')
      } else if (mounted.current) {
        setStatus('offline')
      }
    } finally { saving.current = false }
  }, [canEdit, user?.id, acceptPublished])

  const value = useMemo(() => ({ settings, dark, reduced, status, error, canEdit, dirty: !!draft && canEdit,
    update, publish, discard }), [settings, dark, reduced, status, error, canEdit, draft, update, publish, discard])
  return <Context.Provider value={value}>{children}</Context.Provider>
}
export const useAppearance = () => useContext(Context)
