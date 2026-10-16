// Move the one persistent player view, never create a second audio controller.
export function createPlayerDock(isDesktop = () => typeof window !== 'undefined' && window.matchMedia('(min-width: 901px)').matches) {
  let target = null
  const listeners = new Set()
  const notify = () => listeners.forEach(fn => fn())
  return {
    get: () => isDesktop() ? target : null,
    set: node => { if (target !== node) { target = node; notify() } },
    notify,
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener) },
  }
}
export const playerDock = createPlayerDock()
