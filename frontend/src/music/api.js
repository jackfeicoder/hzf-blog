import { getToken } from '../api.js'

export class MusicApiError extends Error {
  constructor(message, status, gateway = false) {
    super(message)
    this.name = 'MusicApiError'
    this.status = status
    this.gateway = gateway
    this.retryable = [408, 502, 503, 504].includes(status) || (gateway && status === 200)
  }
}

export async function musicApi(path, { method = 'GET', body, signal, timeout = 32000 } = {}) {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) abort()
  signal?.addEventListener('abort', abort, { once: true })
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; abort() }, timeout)
  try {
    const token = getToken()
    const response = await fetch(`/api/music${path}`, {
      method, signal: controller.signal, cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    if (response.status === 204) return null
    let data
    try { data = JSON.parse(await response.text()) }
    catch (e) {
      if (e.name === 'AbortError') throw e
      throw new MusicApiError(response.ok ? '音乐接口响应异常，请刷新重试' : `音乐服务暂时没有响应（${response.status}），请稍后重试或切换平台`, response.status, true)
    }
    if (!response.ok) throw new MusicApiError(typeof data?.detail === 'string' ? data.detail : '操作失败，请重试', response.status)
    return data
  } catch (e) {
    if (!signal?.aborted && (timedOut || e instanceof TypeError)) e.retryable = true
    throw e
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort)
  }
}
