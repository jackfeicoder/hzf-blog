// Trust only the authenticated server capability, never a display name/legacy flag.
export function canManage(user) {
  return user?.can_manage === true
}

export function visibleNavigation(items, user) {
  return items.filter(item => (!item.auth || user) && (!item.admin || canManage(user)))
}

export function adminAccess(user, loading) {
  if (loading) return 'pending'
  return canManage(user) ? 'allowed' : 'denied'
}
