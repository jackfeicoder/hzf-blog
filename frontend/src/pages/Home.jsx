import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import PostCard, { PostCardSkeleton } from '../components/PostCard'
import { avatarText } from '../components/Layout'
import { formatNum } from '../format'
import { useAuth } from '../AuthContext'

export default function Home() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const category = params.get('category') || ''
  const tag = params.get('tag') || ''
  const search = params.get('q') || ''
  const sort = params.get('sort') || 'new'
  const page = Number(params.get('page') || 1)

  const [categories, setCategories] = useState([])
  const [posts, setPosts] = useState([])
  const [total, setTotal] = useState(0)
  const [hot, setHot] = useState([])
  const [authors, setAuthors] = useState([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState(search)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const pageSize = 10

  useEffect(() => {
    let active = true
    setCategories(api.peekCategories() || [])
    setHot(api.peekHotPosts(8) || [])
    setAuthors(api.peekTopAuthors(6) || [])
    api.listCategories().then(data => { if (active) setCategories(data) }).catch(() => {})
    api.hotPosts(8).then(data => { if (active) setHot(data) }).catch(() => {})
    api.topAuthors(6).then(data => { if (active) setAuthors(data) }).catch(() => {})
    return () => { active = false }
  }, [user?.id, retry])

  useEffect(() => {
    let active = true
    const cached = api.peekPosts({ page, page_size: pageSize, category_id: category || undefined, tag: tag || undefined, search: search || undefined, sort })
    setPosts(cached?.items || [])
    setTotal(cached?.total || 0)
    setLoading(!cached)
    setError('')
    api
      .listPosts({
        page,
        page_size: pageSize,
        category_id: category || undefined,
        tag: tag || undefined,
        search: search || undefined,
        sort,
      })
      .then((data) => {
        if (!active) return
        setPosts(data.items)
        setTotal(data.total)
      })
      .catch((e) => { if (active) setError(cached ? '更新失败，当前显示上次加载的内容。' : e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [page, category, tag, search, sort, user?.id, retry])

  useEffect(() => {
    setQ(search)
  }, [search])

  const update = (patch) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => {
      if (v === '' || v == null) next.delete(k)
      else next.set(k, v)
    })
    if (!('page' in patch)) next.delete('page')
    setParams(next)
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="container home-grid">
      <aside className="side-left desktop-only">
        <div className="panel sticky-panel">
          <h3 className="panel-title">分类</h3>
          <button
            type="button"
            className={`cat-item ${!category ? 'active' : ''}`}
            onClick={() => update({ category: '' })}
          >
            全部
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`cat-item ${String(c.id) === category ? 'active' : ''}`}
              onClick={() => update({ category: c.id })}
            >
              <span>{c.name}</span>
              <span className="muted">{c.post_count}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="feed">
        <div className="hero-banner anim-fade">
          <div>
            <h1>发现好技术</h1>
            <p>写文章、点赞收藏、关注作者 · 你的技术社区</p>
          </div>
          <form
            className="hero-search"
            onSubmit={(e) => {
              e.preventDefault()
              update({ q: q.trim() })
            }}
          >
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索文章、技术关键词..."
              enterKeyHint="search"
            />
            <button type="submit" className="btn primary">
              搜索
            </button>
          </form>
        </div>

        <div className="cat-scroll mobile-only">
          <button
            type="button"
            className={`chip ${!category ? 'active' : ''}`}
            onClick={() => update({ category: '' })}
          >
            全部
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`chip ${String(c.id) === category ? 'active' : ''}`}
              onClick={() => update({ category: c.id })}
            >
              {c.name}
            </button>
          ))}
        </div>

        <div className="feed-toolbar">
          <div className="sort-tabs">
            <button
              type="button"
              className={sort === 'new' ? 'active' : ''}
              onClick={() => update({ sort: 'new' })}
            >
              最新
            </button>
            <button
              type="button"
              className={sort === 'hot' ? 'active' : ''}
              onClick={() => update({ sort: 'hot' })}
            >
              最热
            </button>
          </div>
          <form
            className="search-box desktop-only"
            onSubmit={(e) => {
              e.preventDefault()
              update({ q: q.trim() })
            }}
          >
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索文章..."
            />
            <button type="submit" className="btn primary sm">
              搜索
            </button>
          </form>
        </div>

        {(tag || search) && (
          <div className="filter-bar">
            {tag && (
              <span className="filter-chip">
                标签 #{tag}
                <button type="button" onClick={() => update({ tag: '' })}>
                  ×
                </button>
              </span>
            )}
            {search && (
              <span className="filter-chip">
                搜索 “{search}”
                <button
                  type="button"
                  onClick={() => {
                    setQ('')
                    update({ q: '' })
                  }}
                >
                  ×
                </button>
              </span>
            )}
          </div>
        )}

        {error && <div className="filter-bar" role="alert">{error}<button type="button" className="btn ghost sm" onClick={() => { api.invalidatePublicCache(); setRetry(n => n + 1) }}>重试</button></div>}
        {loading ? (
          <>
            <PostCardSkeleton />
            <PostCardSkeleton />
            <PostCardSkeleton />
          </>
        ) : posts.length === 0 ? (
          <div className="empty">暂无文章，去写一篇吧 ✍️</div>
        ) : (
          posts.map((p, i) => <PostCard key={p.id} post={p} index={i} />)
        )}

        {totalPages > 1 && (
          <div className="pager">
            <button type="button" disabled={page <= 1} onClick={() => update({ page: page - 1 })}>
              上一页
            </button>
            <span>
              {page} / {totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => update({ page: page + 1 })}
            >
              下一页
            </button>
          </div>
        )}

        <div className="mobile-discover mobile-only">
          <details className="panel discover-block" open>
            <summary className="panel-title">🔥 热门文章</summary>
            <ol className="rank-list">
              {hot.map((p, i) => (
                <li key={p.id}>
                  <span className={`rank-no n${i + 1}`}>{i + 1}</span>
                  <Link to={`/post/${p.id}`}>{p.title}</Link>
                </li>
              ))}
              {hot.length === 0 && <li className="muted">暂无数据</li>}
            </ol>
          </details>
          <details className="panel discover-block">
            <summary className="panel-title">🏆 作者榜</summary>
            <ul className="author-rank">
              {authors.map((a, i) => (
                <li key={a.user.id}>
                  <span className={`rank-no n${i + 1}`}>{i + 1}</span>
                  <Link to={`/u/${a.user.username}`} className="author-link">
                    <span className="avatar xs">
                      {avatarText(a.user.nickname || a.user.username)}
                    </span>
                    <span>
                      <div>{a.user.nickname || a.user.username}</div>
                      <div className="muted tiny">
                        {a.post_count} 篇 · 👍 {formatNum(a.total_likes)}
                      </div>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </details>
        </div>
      </section>

      <aside className="side-right desktop-only">
        <div className="panel sticky-panel anim-up">
          <h3 className="panel-title">🔥 热门文章</h3>
          <ol className="rank-list">
            {hot.map((p, i) => (
              <li key={p.id}>
                <span className={`rank-no n${i + 1}`}>{i + 1}</span>
                <Link to={`/post/${p.id}`}>{p.title}</Link>
              </li>
            ))}
            {hot.length === 0 && <li className="muted">暂无数据</li>}
          </ol>
        </div>

        <div className="panel sticky-panel anim-up" style={{ animationDelay: '60ms' }}>
          <h3 className="panel-title">🏆 作者榜</h3>
          <ul className="author-rank">
            {authors.map((a, i) => (
              <li key={a.user.id}>
                <span className={`rank-no n${i + 1}`}>{i + 1}</span>
                <Link to={`/u/${a.user.username}`} className="author-link">
                  <span className="avatar xs">{avatarText(a.user.nickname || a.user.username)}</span>
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
      </aside>
    </div>
  )
}
