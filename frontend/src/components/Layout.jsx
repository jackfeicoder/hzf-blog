import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'

function avatarText(name = '') {
  return (name || '?').slice(0, 1).toUpperCase()
}

export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const nav = useNavigate()

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="logo">
            <span className="logo-mark">C</span>
            <span className="logo-text">CodeBlog</span>
          </Link>

          <nav className="nav-links">
            <NavLink to="/" end>首页</NavLink>
            <NavLink to="/rank">排行榜</NavLink>
            {user && <NavLink to="/write">写文章</NavLink>}
          </nav>

          <div className="topbar-right">
            {user ? (
              <>
                <Link to={`/u/${user.username}`} className="user-chip">
                  <span className="avatar sm">{avatarText(user.nickname || user.username)}</span>
                  <span>{user.nickname || user.username}</span>
                </Link>
                <button
                  className="btn ghost sm"
                  onClick={() => {
                    logout()
                    nav('/')
                  }}
                >
                  退出
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className="btn ghost sm">登录</Link>
                <Link to="/register" className="btn primary sm">注册</Link>
              </>
            )}
          </div>
        </div>
      </header>
      <main className="main">{children}</main>
      <footer className="footer">
        <div className="container">
          CodeBlog · 个人技术社区 · React + FastAPI
        </div>
      </footer>
    </div>
  )
}

export { avatarText }
