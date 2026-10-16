import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_APPEARANCE, appearanceKey, normalizeAppearance, readAppearance, writeAppearance, validBackgroundURL, rippleAllowed, glassOpacity } from '../src/appearance/settings.js'

test('defaults and untrusted persisted settings normalize to a fixed schema', () => {
  assert.equal(DEFAULT_APPEARANCE.click_effect,'ripple')
  const result = normalizeAppearance({palette:'wrong',background:'custom',background_url:'javascript:alert(1)',motion:'false',user_id:2})
  assert.deepEqual(result,DEFAULT_APPEARANCE)
  assert.equal(normalizeAppearance({motion:false}).motion,false)
})
test('background URLs allow uploaded images only', () => {
  const path = 'images/202610/'+'a'.repeat(32)+'.webp'
  assert.equal(validBackgroundURL('/uploads/'+path),true)
  assert.equal(validBackgroundURL('https://img.example.test/'+path),true)
  for (const url of ['data:image/png,abc','https://evil.test/track','https://img.test/'+path+'?track=1','https://img.test/'+path+'#x','https://user:pass@img.test/'+path,'/uploads/../../secret']) assert.equal(validBackgroundURL(url),false)
})
test('all accounts and guests share published cache; legacy private caches never override it', () => {
  const map=new Map(), storage={getItem:k=>map.get(k),setItem:(k,v)=>map.set(k,v)}
  const alice=appearanceKey({id:1}), bob=appearanceKey({id:2})
  storage.setItem('blog_appearance_v1:1',JSON.stringify({palette:'violet'}))
  storage.setItem('blog_appearance_v1:1:dirty','1')
  assert.equal(readAppearance(alice,storage).palette,'warm')
  writeAppearance(alice,{palette:'forest',glass_transparency:45},storage)
  assert.equal(readAppearance(alice,storage).palette,'forest')
  assert.equal(readAppearance(bob,storage).palette,'forest')
  assert.equal(readAppearance(appearanceKey(null),storage).glass_transparency,45)
  assert.equal(alice,bob)
  assert.equal(alice,appearanceKey(null))
})
test('malformed storage and quota restrictions preserve usable defaults', () => {
  assert.deepEqual(readAppearance('x',{getItem:()=>'{bad'}),DEFAULT_APPEARANCE)
  const storage={getItem:()=>{throw Error('blocked')},setItem:()=>{throw Error('quota')}}
  assert.doesNotThrow(()=>writeAppearance('x',DEFAULT_APPEARANCE,storage))
})
test('glass transparency has a bounded numeric schema and predictable alpha', () => {
  assert.equal(glassOpacity({glass_transparency:0}),1)
  assert.ok(Math.abs(glassOpacity({glass_transparency:80})-.2)<1e-9)
  assert.equal(glassOpacity({glass_transparency:35}),.65)
  for (const value of [-1,81,Infinity,NaN,'50',null,true,12.5]) assert.equal(normalizeAppearance({glass_transparency:value}).glass_transparency,11)
})
test('ripple ignores dragging, long presses, sliders, disabled controls and right click', () => {
  const start={x:10,y:10,time:100}, end={clientX:12,clientY:10,timeStamp:200,button:0}
  assert.equal(rippleAllowed(start,end,false,false),true)
  for (const e of [{...end,clientX:100},{...end,timeStamp:900},{...end,button:2}]) assert.equal(rippleAllowed(start,e,false,false),false)
  assert.equal(rippleAllowed(start,end,true,false),false)
  assert.equal(rippleAllowed(start,end,false,true),false)
  assert.ok(!rippleAllowed(null,end,false,false))
})
