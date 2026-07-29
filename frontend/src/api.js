const TOKEN_KEY = 'blog_token'

export const getToken = () => sessionStorage.getItem(TOKEN_KEY)
export const setToken = (t) => sessionStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => sessionStorage.removeItem(TOKEN_KEY)

async function request(path, { method = 'GET', body, auth = false } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (auth || getToken()) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
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
    throw new Error(detail)
  }
  if (res.status === 204) return null
  return res.json()
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
  listPosts: ({ page = 1, page_size = 10, category_id, tag, search, author, sort = 'new' } = {}) => {
    const params = new URLSearchParams({ page, page_size, sort })
    if (category_id) params.set('category_id', category_id)
    if (tag) params.set('tag', tag)
    if (search) params.set('search', search)
    if (author) params.set('author', author)
    return request(`/api/posts?${params}`)
  },
  getPost: (id) => request(`/api/posts/${id}`),
  createPost: (data) => request('/api/posts', { method: 'POST', body: data, auth: true }),
  updatePost: (id, data) => request(`/api/posts/${id}`, { method: 'PUT', body: data, auth: true }),
  deletePost: (id) => request(`/api/posts/${id}`, { method: 'DELETE', auth: true }),
  likePost: (id) => request(`/api/posts/${id}/like`, { method: 'POST', auth: true }),
  favoritePost: (id) => request(`/api/posts/${id}/favorite`, { method: 'POST', auth: true }),

  // 分类 / 排行
  listCategories: () => request('/api/categories'),
  hotPosts: (limit = 10) => request(`/api/rankings/posts?limit=${limit}`),
  topAuthors: (limit = 8) => request(`/api/rankings/authors?limit=${limit}`),

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
}
