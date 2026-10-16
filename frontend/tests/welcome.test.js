import test from 'node:test'
import assert from 'node:assert/strict'
import { createWelcomeHistory, shouldShowWelcome, WELCOME_SEEN_KEY, AUTHOR_LINKS, authorIntroduction } from '../src/welcome/policy.js'
import { bioParts } from '../src/bioLinks.js'

const visitor = { pathname:'/', user:null, loading:false, hasToken:false, seen:false }
test('only first anonymous homepage visit opens welcome; existing or pending sessions never do', () => {
  assert.equal(shouldShowWelcome(visitor),true)
  for (const change of [{user:{id:1}}, {loading:true}, {hasToken:true}, {seen:true}]) {
    assert.equal(shouldShowWelcome({...visitor,...change}),false)
  }
})
test('share links, auth pages, manual about and homepage filters/hash are never intercepted', () => {
  for (const pathname of ['/post/5','/music','/videos','/study','/register','/login','/about','/welcome','/u/administrator']) {
    assert.equal(shouldShowWelcome({...visitor,pathname}),false)
  }
  assert.equal(shouldShowWelcome({...visitor,search:'?category=1'}),false)
  assert.equal(shouldShowWelcome({...visitor,hash:'#section'}),false)
})
test('acknowledgement persists across visits without storing account details', () => {
  const values = new Map(), storage={getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)}
  const first = createWelcomeHistory(()=>storage)
  assert.equal(first.hasSeen(),false)
  first.markSeen()
  assert.equal(first.hasSeen(),true)
  assert.equal(createWelcomeHistory(()=>storage).hasSeen(),true)
  assert.deepEqual([...values],[[WELCOME_SEEN_KEY,'1']])
})
test('blocked storage falls back to memory, preventing repeat redirects during a visit', () => {
  const history = createWelcomeHistory(()=>{throw Error('blocked')})
  assert.equal(history.hasSeen(),false)
  assert.doesNotThrow(()=>history.markSeen())
  assert.equal(history.hasSeen(),true)
})
test('social button URLs remain intact; biography summary only removes duplicate official link labels', () => {
  const bio='我是一名计算机专业研究生，热爱编程Github:https://github.com/jackfeicoder;Gitee:https://gitee.com/jackfei2545;CSDN:https://blog.csdn.net/qq_62480054'
  assert.equal(authorIntroduction(bio),'我是一名计算机专业研究生，热爱编程')
  assert.equal(authorIntroduction('学习 jackfeicoder 的代码；保留其他链接 https://example.com'),'学习 jackfeicoder 的代码；保留其他链接 https://example.com')
  assert.equal(AUTHOR_LINKS[0].url,'https://github.com/jackfeicoder')
  assert.equal(AUTHOR_LINKS[1].url,'https://gitee.com/jackfei2545')
  assert.equal(authorIntroduction(null),'')
})
test('biography URL rendering preserves exact text and only links http(s) without embedded credentials', () => {
  const text='Github:https://github.com/jackfeicoder;Gitee:https://gitee.com/jackfei2545；CSDN:https://blog.csdn.net/qq_62480054。'
  const parts=bioParts(text)
  assert.equal(parts.map(part=>part.text).join(''),text)
  assert.deepEqual(parts.filter(part=>part.href).map(part=>part.href),AUTHOR_LINKS.map(link=>link.url))
  for (const value of ['javascript:alert(1)','<img src=x onerror=alert(1)>','https://user:secret@example.com/path']) {
    assert.equal(bioParts(value).some(part=>part.href),false)
    assert.equal(bioParts(value).map(part=>part.text).join(''),value)
  }
  assert.deepEqual(bioParts(''),[])
})
