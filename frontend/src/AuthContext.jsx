import { createContext, useContext, useEffect, useState } from 'react'
import { api, clearToken, getToken, setToken } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    api.me()
      .then(setUser)
      .catch(error => {
        // A slow/offline network must not erase an otherwise valid session.
        if (error.status === 401 || error.status === 403) clearToken()
      })
      .finally(() => setLoading(false))
  }, [])

  const login = async (username, password) => {
    const { access_token } = await api.login(username, password)
    setToken(access_token)
    const me = await api.me()
    setUser(me)
    return me
  }

  const register = async (username, password, nickname) => {
    const { access_token } = await api.register(username, password, nickname)
    setToken(access_token)
    const me = await api.me()
    setUser(me)
    return me
  }

  const logout = () => {
    clearToken()
    setUser(null)
  }

  useEffect(() => {
    const sync = event => {
      if (event.key !== 'blog_token' && event.key !== null) return
      if (!getToken()) { setUser(null); return }
      api.me().then(setUser).catch(error => {
        if (error.status === 401) { clearToken(); setUser(null) }
      })
    }
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
