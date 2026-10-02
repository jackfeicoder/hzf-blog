// OS/container isolation is the security boundary; vm is only LX API compatibility.
const vm = require('node:vm'), crypto = require('node:crypto'), zlib = require('node:zlib')
const readline = require('node:readline')
const output = value => process.stdout.write(JSON.stringify(value) + '\n')
let seq = 0, pending = new Map(), handler, capabilities, initialized = false
const input = readline.createInterface({ input: process.stdin })
const asBuffer = v => Buffer.isBuffer(v) ? v : Buffer.from(v)
input.on('line', async line => {
  try {
    const data = JSON.parse(line)
    if (data.type === 'reply') {
      const callback = pending.get(data.id); pending.delete(data.id)
      if (callback) callback(data.error ? new Error(data.error) : null, data.response, data.response?.body)
      return
    }
    if (initialized) return
    initialized = true
    const lx = {
      EVENT_NAMES: { inited: 'inited', request: 'request', updateAlert: 'updateAlert' }, env: 'desktop', version: '2.0.0',
      currentScriptInfo: { name: data.name, rawScript: data.script, version: '', author: '' },
      on: (event, fn) => { if (event === 'request') handler = fn },
      send: (event, value) => { if (event === 'inited') capabilities = value?.sources },
      request: (url, options, callback) => {
        const id = ++seq
        pending.set(id, callback); output({ type: 'http', id, url, options })
        return () => { pending.delete(id) }
      },
      utils: {
        buffer: { from: (v, enc) => Buffer.from(v, enc), bufToString: (v, enc) => asBuffer(v).toString(enc) },
        crypto: {
          md5: v => crypto.createHash('md5').update(asBuffer(v)).digest('hex'), randomBytes: n => crypto.randomBytes(Math.min(n, 1024)),
          aesEncrypt: (buffer, mode, key, iv) => { const c = crypto.createCipheriv(mode, asBuffer(key), asBuffer(iv)); return Buffer.concat([c.update(asBuffer(buffer)), c.final()]) },
          rsaEncrypt: (buffer, key) => crypto.publicEncrypt({ key, padding: crypto.constants.RSA_NO_PADDING }, asBuffer(buffer)),
        },
        zlib: { inflate: v => zlib.inflateSync(asBuffer(v), { maxOutputLength: 2097152 }), deflate: v => zlib.deflateSync(asBuffer(v)) },
      },
    }
    const context = vm.createContext({ lx, Buffer, setTimeout, clearTimeout, setInterval, clearInterval,
      console: { log() {}, error() {}, warn() {}, info() {}, debug() {} }, URL, URLSearchParams, TextEncoder, TextDecoder })
    vm.runInContext(data.script, context, { timeout: 1500 })
    const start = Date.now()
    while (!capabilities && Date.now() - start < 5000) await new Promise(r => setTimeout(r, 20))
    if (!capabilities || !handler) throw new Error('LX 初始化失败')
    const supported = Object.fromEntries(Object.entries(capabilities).filter(([k,v]) => ['wy','tx','kw','kg','mg'].includes(k) && Array.isArray(v?.actions)).map(([k,v]) => [k, {
      name: k, type: 'music', actions: v.actions.filter(a => ['musicUrl','search','musicSearch','lyric'].includes(a)),
      qualitys: (v.qualitys || []).filter(q => ['128k','320k','flac','flac24bit'].includes(q)),
    }]))
    if (data.action === 'probe') output({ type: 'done', capabilities: supported })
    else {
      const cap = supported[data.source]
      if (!cap?.actions.includes(data.action)) throw new Error('音源不支持该平台')
      const quality = cap.qualitys?.includes(data.info.type) ? data.info.type : cap.qualitys?.[0] || '128k'
      const result = await handler({ source: data.source, action: data.action, info: { ...data.info, type: quality } })
      output({ type: 'done', capabilities: supported, result })
    }
  } catch { output({ type: 'error', message: '音源运行失败或暂时不可用' }) }
})
