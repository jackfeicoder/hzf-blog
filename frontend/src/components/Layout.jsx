import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api } from '../api'

export function avatarText(name = '') {
  return (name || '?').slice(0, 1).toUpperCase()
}

export function UserAvatar({ user, size = 'sm', className = '' }) {
  const avatarUrl = user?.avatar_url
  const name = user?.nickname || user?.username || ''
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={name}
        className={`avatar ${size} avatar-img ${className}`}
        style={{ objectFit: 'cover' }}
        onError={(e) => {
          e.target.style.display = 'none'
        }}
      />
    )
  }
  return <span className={`avatar ${size} ${className}`}>{avatarText(name)}</span>
}

const THEME_KEY = 'blog_theme'

function getInitialTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'dark' || saved === 'light') return saved
    if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark'
  } catch { /* ignore */ }
  return 'light'
}

const navItems = [
  { to: '/', label: '首页', end: true, icon: '🏠' },
  { to: '/rank', label: '排行', icon: '🔥' },
  { to: '/write', label: '写作', icon: '✍️', auth: true },
  { to: '/ai', label: '问 AI', icon: '🤖' },
  { to: '/visitors', label: '访客', icon: '👀' },
  { to: 'https://imagefree.net', label: '画图', icon: '🎨', external: true },
]


export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [theme, setTheme] = useState(getInitialTheme)
  const [progress, setProgress] = useState(0)
  const [showTop, setShowTop] = useState(false)

  // 站内通知状态
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState([])
  const [showNoti, setShowNoti] = useState(false)

  const fetchNotifications = async () => {
    if (!user) return
    try {
      const res = await api.getNotifications()
      if (res) {
        setNotifications(res.items || [])
        setUnreadCount(res.unread_count || 0)
      }
    } catch { /* ignore */ }
  }

  useEffect(() => {
    if (user) fetchNotifications()
  }, [user, location.pathname])

  const onMarkRead = async () => {
    try {
      await api.markNotificationsRead()
      setUnreadCount(0)
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
    } catch { /* ignore */ }
  }

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch { /* ignore */ }
  }, [theme])

  useEffect(() => {
    setMenuOpen(false)
    setShowNoti(false)
  }, [location.pathname, location.search])

  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY || 0
      setScrolled(y > 8)
      setShowTop(y > 420)

      const doc = document.documentElement
      const max = Math.max(doc.scrollHeight - window.innerHeight, 1)
      setProgress(Math.min(100, Math.round((y / max) * 100)))
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [location.pathname])

  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [menuOpen])

  const links = navItems.filter((i) => !i.auth || user)
  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  return (
    <div className="app">
      <div className="reading-progress" style={{ width: `${progress}%` }} />

      <header className={`topbar ${scrolled ? 'is-scrolled' : ''}`}>
        <div className="topbar-inner">
          <button
            type="button"
            className="icon-btn menu-btn"
            aria-label="打开菜单"
            onClick={() => setMenuOpen(true)}
          >
            <span className="hamburger" />
          </button>

          <Link to="/" className="logo">
            <span className="logo-mark">C</span>
            <span className="logo-text">CodeBlog</span>
          </Link>

          <nav className="nav-links desktop-only">
            {links.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="topbar-right">
            <button
              type="button"
              className="theme-toggle"
              onClick={toggleTheme}
              title={theme === 'dark' ? '切换亮色' : '切换暗色'}
              aria-label="切换主题"
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>

            {user && (
              <div className="noti-wrapper" style={{ position: 'relative' }}>
                <button
                  type="button"
                  className="icon-btn noti-bell-btn"
                  onClick={() => setShowNoti(!showNoti)}
                  title="站内消息通知"
                >
                  🔔
                  {unreadCount > 0 && <span className="noti-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>}
                </button>

                {showNoti && (
                  <div className="panel noti-popover">
                    <div className="noti-head">
                      <span>站内消息</span>
                      {unreadCount > 0 && (
                        <button type="button" className="btn-link" onClick={onMarkRead}>
                          全部标为已读
                        </button>
                      )}
                    </div>
                    <div className="noti-list">
                      {notifications.length === 0 ? (
                        <div className="empty sm">暂无系统通知</div>
                      ) : (
                        notifications.map((n) => (
                          <div key={n.id} className={`noti-item ${n.is_read ? 'read' : 'unread'}`}>
                            <UserAvatar user={n.sender} size="xs" />
                            <div className="noti-content">
                              <span className="noti-user">{n.sender?.nickname || n.sender?.username || '系统'}</span>
                              {n.type === 'like' && ' 点赞了你的文章'}
                              {n.type === 'favorite' && ' 收藏了你的文章'}
                              {n.type === 'comment' && ' 评论了你的文章'}
                              {n.type === 'follow' && ' 关注了你'}
                              {n.post && (
                                <Link to={`/post/${n.post.id}`} className="noti-post-title" onClick={() => setShowNoti(false)}>
                                  《{n.post.title}》
                                </Link>
                              )}
                              {n.content && <p className="noti-text">{n.content}</p>}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {user ? (
              <>
                <Link to="/write" className="btn primary sm desktop-only write-btn">
                  写文章
                </Link>
                <Link to={`/u/${user.username}`} className="user-chip">
                  <UserAvatar user={user} size="sm" />
                  <span className="desktop-only">{user.nickname || user.username}</span>
                </Link>
                <button
                  type="button"
                  className="btn ghost sm desktop-only"
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
                <Link to="/login" className="btn ghost sm">
                  登录
                </Link>
                <Link to="/register" className="btn primary sm desktop-only">
                  注册
                </Link>
              </>
            )}
          </div>
        </div>
      </header>


      <div
        className={`drawer-backdrop ${menuOpen ? 'open' : ''}`}
        onClick={() => setMenuOpen(false)}
      />
      <aside className={`drawer ${menuOpen ? 'open' : ''}`} aria-hidden={!menuOpen}>
        <div className="drawer-head">
          <Link to="/" className="logo" onClick={() => setMenuOpen(false)}>
            <span className="logo-mark">C</span>
            <span className="logo-text">CodeBlog</span>
          </Link>
          <button type="button" className="icon-btn" aria-label="关闭" onClick={() => setMenuOpen(false)}>
            ✕
          </button>
        </div>
        {user ? (
          <Link to={`/u/${user.username}`} className="drawer-user" onClick={() => setMenuOpen(false)}>
            <span className="avatar lg">{avatarText(user.nickname || user.username)}</span>
            <div>
              <div className="name">{user.nickname || user.username}</div>
              <div className="muted tiny">@{user.username}</div>
            </div>
          </Link>
        ) : (
          <div className="drawer-auth">
            <Link to="/login" className="btn primary block" onClick={() => setMenuOpen(false)}>
              登录
            </Link>
            <Link to="/register" className="btn ghost block" onClick={() => setMenuOpen(false)}>
              注册
            </Link>
          </div>
        )}
        <nav className="drawer-nav">
          {links.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} onClick={() => setMenuOpen(false)}>
              <span className="nav-ico">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
          {user && (
            <NavLink to={`/u/${user.username}`} onClick={() => setMenuOpen(false)}>
              <span className="nav-ico">👤</span>
              我的主页
            </NavLink>
          )}
          <button type="button" className="btn ghost block" onClick={toggleTheme}>
            {theme === 'dark' ? '☀️ 切换亮色模式' : '🌙 切换暗色模式'}
          </button>
        </nav>
        {user && (
          <button
            type="button"
            className="btn ghost block drawer-logout"
            onClick={() => {
              logout()
              setMenuOpen(false)
              nav('/')
            }}
          >
            退出登录
          </button>
        )}
      </aside>

      <main className="main page-enter" key={location.pathname}>
        {children}
      </main>

      <nav className="bottom-nav mobile-only" aria-label="底部导航">
        <NavLink to="/" end>
          <span>🏠</span>
          首页
        </NavLink>
        <NavLink to="/rank">
          <span>🔥</span>
          排行
        </NavLink>
        <NavLink to={user ? '/write' : '/login'} className="bottom-write">
          <span className="write-fab">＋</span>
          写作
        </NavLink>
        <NavLink to={user ? `/u/${user.username}` : '/login'}>
          <span>👤</span>
          我的
        </NavLink>
      </nav>

      <button
        type="button"
        className={`back-top ${showTop ? 'show' : ''}`}
        onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
        aria-label="回到顶部"
        title="回到顶部"
      >
        ↑
      </button>

      <footer className="footer desktop-only">
        <div className="container">CodeBlog · 技术社区 · React + FastAPI</div>
      </footer>
    </div>
  )
}
