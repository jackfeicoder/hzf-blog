import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server.js'
import NavigationLink from '../src/components/NavigationLink.js'

const render = (location, item) => renderToStaticMarkup(createElement(StaticRouter, { location },
  createElement(NavigationLink, { item }, item.label)))

test('external drawing link has no active class or current-page marker on any blog route', () => {
  for (const location of ['/', '/music', '/rank', '/u/administrator']) {
    const html = render(location, { to: 'https://imagefree.net', label: '画图', external: true })
    assert.match(html, /href="https:\/\/imagefree.net"/)
    assert.match(html, /target="_blank"/)
    assert.match(html, /rel="noopener noreferrer"/)
    assert.doesNotMatch(html, /aria-current|class="active"/)
  }
})
test('internal navigation still selects exactly the matching route', () => {
  assert.match(render('/', { to: '/', end: true, label: '首页' }), /aria-current="page"/)
  assert.doesNotMatch(render('/music', { to: '/', end: true, label: '首页' }), /aria-current/)
  assert.match(render('/music', { to: '/music', label: '听音乐' }), /aria-current="page"/)
})
