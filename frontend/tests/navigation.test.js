import test from 'node:test'
import assert from 'node:assert/strict'
import { canManage, visibleNavigation, adminAccess } from '../src/navigation.js'

const items = [
  { to: '/' }, { to: '/write', auth: true },
  { to: '/visitors', admin: true }, { to: '/admin', admin: true },
]

test('visitor/admin entries are absent for guests, members and legacy administrators', () => {
  for (const user of [null, {}, { username: 'jackfei' }, { is_admin: true }, { can_manage: false }, { can_manage: 'true' }]) {
    assert.equal(canManage(user), false)
    assert.equal(visibleNavigation(items, user).some(item => item.admin), false)
  }
  assert.deepEqual(visibleNavigation(items, null).map(item => item.to), ['/'])
  assert.deepEqual(visibleNavigation(items, { id: 1 }).map(item => item.to), ['/', '/write'])
})

test('server-authorized administrator retains visitor navigation and direct route access', () => {
  const user = { can_manage: true }
  assert.deepEqual(visibleNavigation(items, user), items)
  assert.equal(adminAccess(user, false), 'allowed')
})

test('direct routes wait for session validation and deny non-admins after it finishes', () => {
  for (const user of [null, { can_manage: true }]) assert.equal(adminAccess(user, true), 'pending')
  for (const user of [null, { is_admin: true }, { can_manage: false }]) assert.equal(adminAccess(user, false), 'denied')
})
