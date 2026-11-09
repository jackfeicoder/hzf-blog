import test from 'node:test'
import assert from 'node:assert/strict'
import { filingForHost } from '../src/siteInfo.js'

test('filing is displayed only on the registered domain and its configured aliases', () => {
  for (const host of ['ithzf.xyz', 'www.ithzf.xyz', 'blog.ithzf.xyz', 'ITHZF.XYZ.']) {
    assert.deepEqual(filingForHost(host), { number: '豫ICP备2026026471号', url: 'https://beian.miit.gov.cn/' })
  }
  for (const host of ['', 'localhost', '127.0.0.1', 'blog.120115.xyz', 'ithzf.xyz.example.com']) assert.equal(filingForHost(host), null)
})
