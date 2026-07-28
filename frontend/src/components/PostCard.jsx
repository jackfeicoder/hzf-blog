import { Link } from 'react-router-dom'
import { formatNum, timeAgo } from '../utils'
import { avatarText } from './Layout'

export default function PostCard({ post }) {
  return (
    <article className="post-card">
      <div className="post-card-meta">
        <Link to={`/u/${post.author.username}`} className="author-link">
          <span className="avatar xs">{avatarText(post.author.nickname || post.author.username)}</span>
          <span>{post.author.nickname || post.author.username}</span>
        </Link>
        <span className="dot">·</span>
        <time>{timeAgo(post.created_at)}</time>
        {post.category && (
          <>
            <span className="dot">·</span>
            <Link to={`/?category=${post.category.id}`} className="cat-pill">
              {post.category.name}
            </Link>
          </>
        )}
        {!post.published && <span className="draft-badge">草稿</span>}
      </div>

      <Link to={`/post/${post.id}`} className="post-card-title">
        {post.title}
      </Link>

      {post.summary && <p className="post-card-summary">{post.summary}</p>}

      <div className="post-card-footer">
        <div className="tag-list">
          {post.tags?.slice(0, 4).map((t) => (
            <Link key={t.id} to={`/?tag=${encodeURIComponent(t.name)}`} className="tag">
              #{t.name}
            </Link>
          ))}
        </div>
        <div className="stat-row">
          <span title="阅读">👁 {formatNum(post.views)}</span>
          <span title="点赞">👍 {formatNum(post.like_count)}</span>
          <span title="评论">💬 {formatNum(post.comment_count)}</span>
          <span title="收藏">⭐ {formatNum(post.favorite_count)}</span>
        </div>
      </div>
    </article>
  )
}
