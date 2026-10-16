import { useEffect, useRef, useState } from 'react'
import { useAppearance } from './AppearanceContext'
import { rippleAllowed } from './settings'

export default function AppearanceHost() {
  const { settings, reduced } = useAppearance()
  const host = useRef(null)
  const [loaded, setLoaded] = useState('')
  const [failed, setFailed] = useState('')
  const url = settings.background === 'custom' ? settings.background_url : ''
  useEffect(() => {
    if (reduced || settings.click_effect === 'none') return
    const nodes = new Map(), starts = new Map()
    const remove = node => { clearTimeout(nodes.get(node)); nodes.delete(node); node.remove() }
    const blocked = target => !(target instanceof Element) || !!target.closest('input,textarea,select,[contenteditable="true"],[disabled],[aria-disabled="true"],[role="slider"]')
    const down = e => {
      if (!blocked(e.target) && e.button === 0) starts.set(e.pointerId, { x: e.clientX, y: e.clientY, time: e.timeStamp })
    }
    const cancel = e => starts.delete(e.pointerId)
    const up = e => {
      const start = starts.get(e.pointerId)
      cancel(e)
      if (!rippleAllowed(start, e, false, blocked(e.target))) return
      while (nodes.size >= 6) remove(nodes.keys().next().value)
      const node = document.createElement('span')
      node.className = `click-${settings.click_effect}`
      node.style.left = `${e.clientX}px`
      node.style.top = `${e.clientY}px`
      if (settings.click_effect === 'stars') node.textContent = '✧'
      // Native dialogs occupy the top layer: render inside the visible dialog
      // rather than behind it. Only decorative DOM is mutated, never React UI.
      const dialog = e.target.closest('dialog[open]')
      ;(dialog?.querySelector('.appearance-dialog-effects') || host.current)?.appendChild(node)
      nodes.set(node, setTimeout(() => remove(node), 650))
      node.addEventListener('animationend', () => remove(node), { once: true })
    }
    document.addEventListener('pointerdown', down, { passive: true, capture: true })
    document.addEventListener('pointerup', up, { passive: true, capture: true })
    document.addEventListener('pointercancel', cancel, { passive: true, capture: true })
    const blur = () => starts.clear()
    // No pointermove loop, canvas, timers per frame, or React rerenders.
    window.addEventListener('blur', blur)
    return () => {
      document.removeEventListener('pointerdown', down, true)
      document.removeEventListener('pointerup', up, true)
      document.removeEventListener('pointercancel', cancel, true)
      window.removeEventListener('blur', blur)
      for (const node of nodes.keys()) remove(node)
    }
  }, [settings.click_effect, reduced])
  return <>
    <div className="appearance-wallpaper" aria-hidden="true">
      {url && failed !== url && <img src={url} alt="" decoding="async" loading="lazy" fetchPriority="low"
        className={loaded === url ? 'loaded' : ''} onLoad={() => setLoaded(url)} onError={() => setFailed(url)} />}
    </div>
    <div ref={host} className="appearance-effects" aria-hidden="true" />
  </>
}
