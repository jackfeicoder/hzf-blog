import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const player = readFileSync(new URL('../src/music/music.css', import.meta.url), 'utf8')
const layout = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')
function layer(css, selector) {
  const blocks = [...css.matchAll(new RegExp(`\\.${selector}\\s*\\{([^}]+)\\}`, 'g'))]
  const values = blocks.flatMap(block => [...block[1].matchAll(/z-index\s*:\s*(\d+)/g)].map(match => Number(match[1])))
  assert.ok(values.length, `Missing z-index for ${selector}`)
  return values.at(-1)
}

test('mini player and queue stay below drawer and its interaction-blocking backdrop', () => {
  const bar = layer(player, 'music-player-bar'), queue = layer(player, 'music-queue-popover')
  const backdrop = layer(layout, 'drawer-backdrop'), drawer = layer(layout, 'drawer')
  assert.ok(layer(layout, 'bottom-nav') < bar)
  assert.ok(bar < queue)
  assert.ok(queue < backdrop)
  assert.ok(backdrop < drawer)
})
