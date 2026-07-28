import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { avatarText } from '../components/Layout'
import { formatNum } from '../utils'

export default function Rank() {
  const [hot, setHot] = useState([])
  const [authors, setAuthors] = useState([])

  useEffect(() => {
    api.hotPosts(20).then(setHot).catch(() => {})
    api.topAuthors(15).then(setAuthors).catch(() => {})
  }, [])

  return (
    <div className="container rank-page">
      <div className="panel">
        <h2 className="panel-title">🔥 热门文章 TOP 20</h2>
        <ol className="rank-list big">
          {hot.map((p, i) => (
            <li key={p.id}>
              <span className={`rank-no n${i + 1}`}>{i + 1}</span>
              <div className="rank-main">
                <Link to={`/post/${p.id}`} className="rank-title">
                  {p.title}
                </Link>
                <div className="muted tiny">
                  {p.author.nickname || p.author.username} · 👁 {formatNum(p.views)} · 👍{' '}
                  {formatNum(p.like_count)} · 💬 {formatNum(p.comment_count)}
                </div>
              </div>
            </li>
          ))}
          {hot.length === 0 && <li className="muted">暂无数据</li>}
        </ol>
      </div>

      <div className="panel">
        <h2 className="panel-title">🏆 作者影响力榜</h2>
        <ul className="author-rank big">
          {authors.map((a, i) => (
            <li key={a.user.id}>
              <span className={`rank-no n${i + 1}`}>{i + 1}</span>
              <Link to={`/u/${a.user.username}`} className="author-link">
                <span className="avatar sm">{avatarText(a.user.nickname || a.user.username)}</span>
                <span>
                  <div>{a.user.nickname || a.user.username}</div>
                  <div className="muted tiny">
                    {a.post_count} 篇 · 👍 {formatNum(a.total_likes)} · 👁 {formatNum(a.total_views)}
                  </div>
                </span>
              </Link>
            </li>
          ))}
          {authors.length === 0 && <li className="muted">暂无数据</li>}
        </ul>
      </div>
    </div>
  )
}
