// Trust only the authenticated server capability, never a display name/legacy flag.
export function canManage(user) {
  return user?.can_manage === true
}

export function visibleNavigation(items, user) {
  return items.filter(item => (user || ['/', '/login', '/register', '/welcome'].includes(item.to)) && (!item.auth || user) && (!item.admin || canManage(user)))
}

export function adminAccess(user, loading) {
  if (loading) return 'pending'
  return canManage(user) ? 'allowed' : 'denied'
}

export function pageAccess(pathname, user, loading) {
  if (['/', '/login', '/register', '/welcome'].includes(pathname.replace(/\/+$/, '') || '/')) return 'allowed'
  if (loading) return 'pending'
  return user ? 'allowed' : 'denied'
}
