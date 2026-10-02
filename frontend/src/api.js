import { QueryCache } from './queryCache.js'

const TOKEN_KEY = 'blog_token'
const publicCache = new QueryCache()
const videoCache = new QueryCache()
let cacheToken
export const invalidatePublicCache = () => { publicCache.clear(); videoCache.clear() }

function syncCacheSession() {
  const token = getToken()
  if (token !== cacheToken) {
    invalidatePublicCache()
    cacheToken = token
  }
}

function cached(path) {
  syncCacheSession()
  return publicCache.read(path, () => request(path))
}

function peek(path) {
  syncCacheSession()
  return publicCache.peek(path)
}

function postsPath({ page = 1, page_size = 10, category_id, tag, search, author, sort = 'new' } = {}) {
  const params = new URLSearchParams({ page, page_size, sort })
  if (category_id) params.set('category_id', category_id)
  if (tag) params.set('tag', tag)
  if (search) params.set('search', search)
  if (author) params.set('author', author)
  return `/api/posts?${params}`
}

// 持久化到 localStorage：关浏览器后再开仍保持登录
// 同时清理旧的 sessionStorage，避免两处不一致
export const getToken = () => {
  try {
    const t = localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY)
    if (t && !localStorage.getItem(TOKEN_KEY)) {
      localStorage.setItem(TOKEN_KEY, t)
      sessionStorage.removeItem(TOKEN_KEY)
    }
    return t
  } catch {
    return null
  }
}

export const setToken = (t) => {
  invalidatePublicCache()
  try {
    localStorage.setItem(TOKEN_KEY, t)
    sessionStorage.removeItem(TOKEN_KEY)
  } catch { /* private mode etc. */ }
}

export const clearToken = () => {
  invalidatePublicCache()
  try {
    localStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(TOKEN_KEY)
  } catch { /* ignore */ }
}

async function request(path, { method = 'GET', body, auth = false } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (auth || getToken()) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  const controller = method === 'GET' ? new AbortController() : null
  const timer = controller ? setTimeout(() => controller.abort(), 15_000) : null
  try {
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: controller?.signal,
  })
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`
    try {
      const data = await res.json()
      if (data.detail) {
        if (typeof data.detail === 'string') {
          detail = data.detail
        } else if (Array.isArray(data.detail)) {
          // FastAPI / Pydantic 422: [{loc, msg, type}, ...]
          detail = data.detail
            .map((e) => {
              const field = Array.isArray(e.loc) ? e.loc.slice(1).join('.') : ''
              const msg = e.msg || e.message || JSON.stringify(e)
              return field ? `${field}: ${msg}` : msg
            })
            .join('；')
        } else {
          detail = JSON.stringify(data.detail)
        }
      }
    } catch { /* ignore */ }
    const error = new Error(detail)
    error.status = res.status
    throw error
  }
  if (method !== 'GET' && /^\/api\/(posts|users|auth|admin|comments)(\/|\?|$)/.test(path)) invalidatePublicCache()
  if (method !== 'GET' && path.startsWith('/api/media/videos')) videoCache.clear()
  if (res.status === 204) return null
  return await res.json()
  } catch (error) {
    if (controller?.signal.aborted) throw new Error('加载超时，请稍后重试或检查网络线路')
    throw error
  } finally {
    if (timer) clearTimeout(timer)
  }
}

export const api = {
  // 认证
  register: (username, password, nickname) =>
    request('/api/auth/register', { method: 'POST', body: { username, password, nickname } }),
  login: (username, password) =>
    request('/api/auth/login', { method: 'POST', body: { username, password } }),
  me: () => request('/api/auth/me', { auth: true }),
  updateMe: (data) => request('/api/auth/me', { method: 'PUT', body: data, auth: true }),

  // 文章
  listPosts: (params = {}) => params.author ? request(postsPath(params)) : cached(postsPath(params)),
  peekPosts: (params = {}) => params.author ? undefined : peek(postsPath(params)),
  peekCategories: () => peek('/api/categories'),
  peekHotPosts: (limit = 10) => peek(`/api/rankings/posts?limit=${limit}`),
  peekTopAuthors: (limit = 8) => peek(`/api/rankings/authors?limit=${limit}`),
  invalidatePublicCache,
  getPost: (id) => request(`/api/posts/${id}`),
  createPost: (data) => request('/api/posts', { method: 'POST', body: data, auth: true }),
  updatePost: (id, data) => request(`/api/posts/${id}`, { method: 'PUT', body: data, auth: true }),
  deletePost: (id, password) => request(`/api/posts/${id}`, { method: 'DELETE', body: { password }, auth: true }),
  likePost: (id) => request(`/api/posts/${id}/like`, { method: 'POST', auth: true }),
  favoritePost: (id) => request(`/api/posts/${id}/favorite`, { method: 'POST', auth: true }),

  // 分类 / 排行
  adminRequest: (path, options = {}) => request(`/api/admin${path}`, { ...options, auth: true }),
  listCategories: () => cached('/api/categories'),
  hotPosts: (limit = 10) => cached(`/api/rankings/posts?limit=${limit}`),
  topAuthors: (limit = 8) => cached(`/api/rankings/authors?limit=${limit}`),

  // 评论
  listComments: (postId) => request(`/api/posts/${postId}/comments`),
  addComment: (postId, data) =>
    request(`/api/posts/${postId}/comments`, { method: 'POST', body: data, auth: true }),
  deleteComment: (id) => request(`/api/comments/${id}`, { method: 'DELETE', auth: true }),

  // 用户
  getUser: (username) => request(`/api/users/${encodeURIComponent(username)}`),
  followUser: (username) =>
    request(`/api/users/${encodeURIComponent(username)}/follow`, { method: 'POST', auth: true }),
  userFavorites: (username, page = 1) =>
    request(`/api/users/${encodeURIComponent(username)}/favorites?page=${page}`),

  // AI 问答
  getChatProviders: () => request('/api/chat/providers'),
  sendChat: (data) => request('/api/chat', { method: 'POST', body: data }),

  // 图片与头像上传
  uploadImage: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    const headers = {}
    if (getToken()) headers.Authorization = `Bearer ${getToken()}`
    const res = await fetch('/api/upload/image', { method: 'POST', headers, body: formData })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || '图片上传失败')
    }
    return res.json()
  },

  uploadAvatar: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    const headers = {}
    if (getToken()) headers.Authorization = `Bearer ${getToken()}`
    const res = await fetch('/api/upload/avatar', { method: 'POST', headers, body: formData })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || '头像上传失败')
    }
    invalidatePublicCache()
    return res.json()
  },

  // 消息通知
  getNotifications: () => request('/api/notifications', { auth: true }),
  markNotificationsRead: () => request('/api/notifications/read-all', { method: 'POST', auth: true }),

  // 访客统计
  getVisitors: () => request('/api/visitors'),

  videoLinks: () => { syncCacheSession(); return videoCache.read('videos', () => request('/api/media/videos')) },
  peekVideoLinks: () => { syncCacheSession(); return videoCache.peek('videos') },
  refreshVideoLinks: () => videoCache.clear(),
  saveVideoLink: ({ id, ...data }) => request(`/api/media/videos${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', body: data, auth: true }),
  deleteVideoLink: (id) => request(`/api/media/videos/${id}`, { method: 'DELETE', auth: true }),

  studyToday: () => request('/api/study/today', { auth: true }),
  studyTask: (key, data) => request(`/api/study/today/tasks/${encodeURIComponent(key)}`, { method: 'PUT', body: data, auth: true }),
  studyProgress: () => request('/api/study/progress', { auth: true }),
  studyHistory: (month) => request(`/api/study/history?month=${month}`, { auth: true }),
  studyNextRound: (kind, mode) => request(`/api/study/rounds/${kind}/next`, { method: 'POST', body: { mode }, auth: true }),
  studyBank: () => request('/api/study/bank', { auth: true }),
  studySaveItem: (data) => request(`/api/study/bank${data.id ? `/${data.id}` : ''}`, { method: data.id ? 'PUT' : 'POST', body: data, auth: true }),
  studyPreview: (post_id, kind) => request('/api/study/bank/preview', { method: 'POST', body: { post_id, kind }, auth: true }),
  studyImport: (items) => request('/api/study/bank/import', { method: 'POST', body: { items }, auth: true }),

  // AI 聊天流式接口
  sendChatStream: (data) =>
    fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
}





