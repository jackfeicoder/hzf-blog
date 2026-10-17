import test from 'node:test'
import assert from 'node:assert/strict'
import { waitForRetry } from '../src/music/retry.js'

test('retry wait is abortable immediately and while waiting', async()=>{
  const first=new AbortController(); first.abort()
  await assert.rejects(waitForRetry(30000,first.signal),e=>e.name==='AbortError')
  const second=new AbortController(); const waiting=waitForRetry(30000,second.signal); second.abort()
  await assert.rejects(waiting,e=>e.name==='AbortError')
  await waitForRetry(0,new AbortController().signal)
})
