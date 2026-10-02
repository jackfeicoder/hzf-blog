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
    const data = await response.json()
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请重试')
    return data
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort)
  }
}
