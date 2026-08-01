import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { UserAvatar } from '../components/Layout'
import { formatNum, timeAgo } from '../utils'

export default function Visitors() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const loadData = async () => {
    try {
      setLoading(true)
      const res = await api.getVisitors()
      setData(res)
    } catch (e) {
      setErr(e.message || '加载访客记录失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  if (err) return <div className="container empty">{err}</div>

  return (
    <div className="container visitors-page">
      <div className="visitors-header-banner card">
        <div className="banner-left">
          <h2>👀 实时访客记录与足迹看板</h2>
          <p className="muted">记录全站真实访问轨迹，已登录用户显示个人主页，未登录显示游客 IP</p>
        </div>
        <button
          type="button"
          className="btn ghost sm"
          onClick={loadData}
          disabled={loading}
        >
          {loading ? '刷新中...' : '🔄 刷新实时流'}
        </button>
      </div>

      {/* 数据统计卡片 */}
      <div className="visitor-stats-grid">
        <div className="card stat-card">
          <div className="stat-icon">📊</div>
          <div className="stat-info">
            <span className="stat-num">{formatNum(data?.total_visits || 0)}</span>
            <span className="stat-label">全站累计访问次</span>
          </div>
        </div>

        <div className="card stat-card">
          <div className="stat-icon">🌐</div>
          <div className="stat-info">
            <span className="stat-num">{formatNum(data?.today_ip_count || 0)}</span>
            <span className="stat-label">今日独立 IP 数</span>
          </div>
        </div>

        <div className="card stat-card">
          <div className="stat-icon">🔥</div>
          <div className="stat-info">
            <span className="stat-num">{formatNum(data?.today_visit_count || 0)}</span>
            <span className="stat-label">今日访问总频次</span>
          </div>
        </div>
      </div>

      {/* 实时访客数据流 */}
      <div className="card visitors-list-card">
        <div className="list-title-bar">
          <h3>⚡ 最新 100 访客日志记录</h3>
          <span className="live-badge">● 实时更新中</span>
        </div>

        {loading && !data ? (
          <div className="empty">加载访客日志中...</div>
        ) : (
          <div className="visitor-table-wrapper">
            <table className="visitor-table">
              <thead>
                <tr>
                  <th>访客身份</th>
                  <th>IP 地址</th>
                  <th>访问路径</th>
                  <th>访问时间</th>
                </tr>
              </thead>
              <tbody>
                {data?.items?.map((item) => (
                  <tr key={item.id} className={item.is_guest ? 'row-guest' : 'row-user'}>
                    <td>
                      {item.is_guest ? (
                        <div className="user-cell guest-cell">
                          <span className="avatar xs guest-avatar">👤</span>
                          <span className="guest-tag">游客 ({item.ip})</span>
                        </div>
                      ) : (
                        <Link to={`/u/${item.user?.username}`} className="user-cell author-link">
                          <UserAvatar user={item.user} size="xs" />
                          <span className="user-name">{item.display_name}</span>
                          <span className="muted tiny">@{item.user?.username}</span>
                        </Link>
                      )}
                    </td>
                    <td>
                      <code className="ip-code">{item.ip}</code>
                    </td>
                    <td>
                      <span className="path-chip">{item.path}</span>
                    </td>
                    <td>
                      <time className="time-text">{timeAgo(item.created_at)}</time>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
