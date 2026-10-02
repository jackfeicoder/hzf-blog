import test from 'node:test'
import assert from 'node:assert/strict'
import { isLyricsTap } from '../src/music/logic.js'

test('mobile player opens lyrics for links/text/blank space, not native controls', () => {
  for (const tag of ['a', 'small', 'span', 'div']) {
    assert.equal(isLyricsTap({ target: { closest: () => null } }, true), true, tag)
  }
  for (const tag of ['button', 'input', 'select', 'label', 'role=button']) {
    assert.equal(isLyricsTap({ target: { closest: selector => { assert.match(selector, /button.*input.*select/); return tag } } }, true), false)
  }
})
test('desktop and modified links retain normal navigation behavior', () => {
  const event = { target: { closest: () => null } }
  assert.equal(isLyricsTap(event, false), false)
  for (const modifier of ['ctrlKey', 'metaKey', 'shiftKey', 'altKey']) {
    assert.equal(isLyricsTap({ ...event, [modifier]: true }, true), false)
  }
})
