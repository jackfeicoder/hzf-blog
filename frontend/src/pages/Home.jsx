import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import PostCard from '../components/PostCard'
import { avatarText } from '../components/Layout'
import { formatNum } from '../utils'

export default function Home() {
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
  const pageSize = 10

  useEffect(() => {
    api.listCategories().then(setCategories).catch(() => {})
    api.hotPosts(8).then(setHot).catch(() => {})
    api.topAuthors(6).then(setAuthors).catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
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
        setPosts(data.items)
        setTotal(data.total)
      })
      .catch((e) => console.error(e))
      .finally(() => setLoading(false))
  }, [page, category, tag, search, sort])

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
      <aside className="side-left">
        <div className="panel">
          <h3 className="panel-title">分类</h3>
          <button
            className={`cat-item ${!category ? 'active' : ''}`}
            onClick={() => update({ category: '' })}
          >
            全部
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
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
        <div className="feed-toolbar">
          <div className="sort-tabs">
            <button className={sort === 'new' ? 'active' : ''} onClick={() => update({ sort: 'new' })}>
              最新
            </button>
            <button className={sort === 'hot' ? 'active' : ''} onClick={() => update({ sort: 'hot' })}>
              最热
            </button>
          </div>
          <form
            className="search-box"
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
            <button type="submit" className="btn primary sm">搜索</button>
          </form>
        </div>

        {(tag || search) && (
          <div className="filter-bar">
            {tag && (
              <span className="filter-chip">
                标签 #{tag}
                <button onClick={() => update({ tag: '' })}>×</button>
              </span>
            )}
            {search && (
              <span className="filter-chip">
                搜索 “{search}”
                <button onClick={() => { setQ(''); update({ q: '' }) }}>×</button>
              </span>
            )}
          </div>
        )}

        {loading ? (
          <div className="empty">加载中...</div>
        ) : posts.length === 0 ? (
          <div className="empty">暂无文章，去写一篇吧 ✍️</div>
        ) : (
          posts.map((p) => <PostCard key={p.id} post={p} />)
        )}

        {totalPages > 1 && (
          <div className="pager">
            <button disabled={page <= 1} onClick={() => update({ page: page - 1 })}>
              上一页
            </button>
            <span>
              {page} / {totalPages}
            </span>
            <button disabled={page >= totalPages} onClick={() => update({ page: page + 1 })}>
              下一页
            </button>
          </div>
        )}
      </section>

      <aside className="side-right">
        <div className="panel">
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

        <div className="panel">
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
