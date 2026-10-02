import { getToken } from '../api.js'

export async function musicApi(path, { method = 'GET', body, signal, timeout = 32000 } = {}) {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) abort()
  signal?.addEventListener('abort', abort, { once: true })
  const timer = setTimeout(abort, timeout)
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
      throw new Error(response.ok ? '音乐接口响应异常，请刷新重试' : `音乐服务暂时没有响应（${response.status}），请稍后重试或切换平台`)
    }
    if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : '操作失败，请重试')
    return data
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort)
  }
}
