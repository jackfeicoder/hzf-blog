import test from 'node:test'
import assert from 'node:assert/strict'
import { availableModel, DEFAULT_CHAT_MODEL, readChatEvents } from '../src/chat/config.js'

test('retired or missing saved models follow the provider default', () => {
  const provider = {id:'sensenova',models:[DEFAULT_CHAT_MODEL,'kimi-k3'],default_model:DEFAULT_CHAT_MODEL}
  assert.equal(availableModel('sensenova-6.7-flash-lite',provider),DEFAULT_CHAT_MODEL)
  assert.equal(availableModel('kimi-k3',provider),'kimi-k3')
  assert.equal(availableModel('retired',{...provider,models:['future'],default_model:'retired'}),'future')
  assert.equal(availableModel('private',{id:'custom',models:[]}), 'private')
  assert.equal(availableModel('',{id:'sensenova',models:[]}), '')
})

function responseFor(text, width=1) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream({start(controller) {
    for(let at=0;at<bytes.length;at+=width) controller.enqueue(bytes.slice(at,at+width))
    controller.close()
  }}))
}

test('SSE survives arbitrary UTF-8/chunk boundaries and accepts no space after data', async () => {
  const events=[]
  await readChatEvents(responseFor('data:{"model":"new"}\r\n\r\ndata: {"content":"连接成功"}\r\n\r\ndata:[DONE]\r\n\r\ndata:{"content":"ignored"}\n\n'), event=>events.push(event))
  assert.deepEqual(events,[{model:'new'},{content:'连接成功'}])
})
test('SSE error propagates and does not leave a false thinking state', async () => {
  await assert.rejects(readChatEvents(responseFor('data:{"error":"额度限制（429）"}\n\n',3),()=>{}),/429/)
})
test('SSE flushes a final event without a trailing newline', async () => {
  const events=[]
  await readChatEvents(responseFor('data:{"content":"完成"}',5), event=>events.push(event))
  assert.deepEqual(events,[{content:'完成'}])
})
