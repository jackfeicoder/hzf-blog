import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../AuthContext'
import { UserAvatar } from '../components/Layout'
import { bindCodeCopy, formatNum, renderMarkdown, timeAgo } from '../utils'

export default function PostPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const nav = useNavigate()

  const [post, setPost] = useState(null)
  const [comments, setComments] = useState([])
  const [content, setContent] = useState('')
  const [replyTo, setReplyTo] = useState(null)
  const [err, setErr] = useState('')
  const [following, setFollowing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toc, setToc] = useState([])
  const [activeTocId, setActiveTocId] = useState('')
  const mdRef = useRef(null)

  const load = async () => {
    const p = await api.getPost(id)
    setPost(p)
    const cs = await api.listComments(id)
    setComments(cs)
    if (user && p.author.username !== user.username) {
      try {
        const profile = await api.getUser(p.author.username)
        setFollowing(profile.is_following)
      } catch { /* ignore */ }
    }
  }

  useEffect(() => {
    load().catch((e) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, user?.id])

  const html = useMemo(() => renderMarkdown(post?.content || ''), [post?.content])

  useEffect(() => {
    if (!mdRef.current) return
    bindCodeCopy(mdRef.current)

    // 提取 TOC 标题大纲
    const nodes = mdRef.current.querySelectorAll('h1, h2, h3')
    const list = []
    nodes.forEach((node, index) => {
      if (!node.id) {
        node.id = `heading-auto-${index}`
      }
      list.push({
        id: node.id,
        text: node.textContent || '',
        level: Number(node.tagName.replace('H', '')),
      })
    })
    setToc(list)

    // 图片加载失败处理
    mdRef.current.querySelectorAll('img').forEach((img) => {
      if (img.dataset.errBound) return
      img.dataset.errBound = '1'
      img.addEventListener('error', () => {
        img.classList.add('is-broken')
        if (!img.alt) img.alt = '图片加载失败'
      })
    })
  }, [html])

  // 监听滚动高亮当前 TOC 节点
  useEffect(() => {
    if (toc.length === 0) return
    const onScroll = () => {
      const scrollY = window.scrollY || 0
      let currentId = ''
      for (const item of toc) {
        const el = document.getElementById(item.id)
        if (el && el.offsetTop - 100 <= scrollY) {
          currentId = item.id
        }
      }
      if (currentId) setActiveTocId(currentId)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [toc])

  const tree = useMemo(() => {
    const tops = comments.filter((c) => !c.parent_id)
    const replies = comments.filter((c) => c.parent_id)
    return tops.map((t) => ({
      ...t,
      children: replies.filter((r) => r.parent_id === t.id),
    }))
  }, [comments])

  if (err) return <div className="container empty">{err}</div>
  if (!post) return <div className="container empty">加载中...</div>

  const isOwner = user && (user.id === post.author.id || user.is_admin)

  const onLike = async () => {
    if (!user) return nav('/login')
    const r = await api.likePost(post.id)
    setPost({ ...post, liked: r.active, like_count: r.count })
  }
  const onFavorite = async () => {
    if (!user) return nav('/login')
    const r = await api.favoritePost(post.id)
    setPost({ ...post, favorited: r.active, favorite_count: r.count })
  }
  const onFollow = async () => {
    if (!user) return nav('/login')
    const r = await api.followUser(post.author.username)
    setFollowing(r.active)
  }
  const onDelete = async () => {
    if (!confirm('确认删除这篇文章？')) return
    await api.deletePost(post.id)
    nav('/')
  }
  const onSubmitComment = async (e) => {
    e.preventDefault()
    if (!user) return nav('/login')
    if (!content.trim()) return
    setBusy(true)
    try {
      await api.addComment(post.id, {
        content: content.trim(),
        parent_id: replyTo?.parent_id || null,
        reply_to: replyTo?.reply_to || '',
      })
      setContent('')
      setReplyTo(null)
      const cs = await api.listComments(id)
      setComments(cs)
      setPost({ ...post, comment_count: post.comment_count + 1 })
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }
  const onDeleteComment = async (cid) => {
    if (!confirm('删除这条评论？')) return
    await api.deleteComment(cid)
    const cs = await api.listComments(id)
    setComments(cs)
  }

  const scrollToHeading = (id) => {
    const el = document.getElementById(id)
    if (el) {
      const top = el.getBoundingClientRect().top + window.scrollY - 70
      window.scrollTo({ top, behavior: 'smooth' })
    }
  }

  return (
    <div className="container post-layout">
      <article className="post-main panel">
        <h1 className="post-title">{post.title}</h1>
        <div className="post-meta">
          <Link to={`/u/${post.author.username}`} className="author-link">
            <UserAvatar user={post.author} size="sm" />
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
          <span className="dot">·</span>
          <span className="muted">阅读 {formatNum(post.views)}</span>
          {isOwner && (
            <span className="owner-actions">
              <Link to={`/edit/${post.id}`} className="btn ghost sm">编辑</Link>
              <button className="btn danger sm" onClick={onDelete}>删除</button>
            </span>
          )}
        </div>

        <div className="tag-list" style={{ marginBottom: 16 }}>
          {post.tags?.map((t) => (
            <Link key={t.id} to={`/?tag=${encodeURIComponent(t.name)}`} className="tag">
              #{t.name}
            </Link>
          ))}
        </div>

        <div
          ref={mdRef}
          className="markdown-body"
          dangerouslySetInnerHTML={{ __html: html }}
        />

        <div className="action-bar">
          <button className={`action-btn ${post.liked ? 'on' : ''}`} onClick={onLike}>
            👍 点赞 {formatNum(post.like_count)}
          </button>
          <button className={`action-btn ${post.favorited ? 'on' : ''}`} onClick={onFavorite}>
            ⭐ 收藏 {formatNum(post.favorite_count)}
          </button>
          <span className="muted">💬 评论 {formatNum(post.comment_count)}</span>
        </div>

        <section className="comments">
          <h3>评论 {comments.length}</h3>
          <form className="comment-form" onSubmit={onSubmitComment}>
            {replyTo && (
              <div className="reply-tip">
                回复 @{replyTo.label}
                <button type="button" onClick={() => setReplyTo(null)}>取消</button>
              </div>
            )}
            <textarea
              rows={3}
              placeholder={user ? '写下你的想法...' : '登录后发表评论'}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              disabled={!user}
            />
            <button className="btn primary" disabled={!user || busy}>
              {busy ? '发送中...' : '发表评论'}
            </button>
          </form>

          <div className="comment-list">
            {tree.map((c) => (
              <div key={c.id} className="comment-item">
                <div className="comment-head">
                  <Link to={`/u/${c.author.username}`} className="author-link">
                    <UserAvatar user={c.author} size="xs" />
                    <strong>{c.author.nickname || c.author.username}</strong>
                  </Link>
                  <time className="muted">{timeAgo(c.created_at)}</time>
                </div>
                <p className="comment-body">{c.content}</p>
                <div className="comment-actions">
                  {user && (
                    <button
                      onClick={() =>
                        setReplyTo({
                          parent_id: c.id,
                          reply_to: c.author.nickname || c.author.username,
                          label: c.author.nickname || c.author.username,
                        })
                      }
                    >
                      回复
                    </button>
                  )}
                  {(user?.id === c.author.id || isOwner) && (
                    <button onClick={() => onDeleteComment(c.id)}>删除</button>
                  )}
                </div>
                {c.children?.length > 0 && (
                  <div className="comment-replies">
                    {c.children.map((r) => (
                      <div key={r.id} className="comment-item reply">
                        <div className="comment-head">
                          <Link to={`/u/${r.author.username}`} className="author-link">
                            <UserAvatar user={r.author} size="xs" />
                            <strong>{r.author.nickname || r.author.username}</strong>
                          </Link>
                          {r.reply_to && <span className="muted">回复 @{r.reply_to}</span>}
                          <time className="muted">{timeAgo(r.created_at)}</time>
                        </div>
                        <p className="comment-body">{r.content}</p>
                        <div className="comment-actions">
                          {user && (
                            <button
                              onClick={() =>
                                setReplyTo({
                                  parent_id: c.id,
                                  reply_to: r.author.nickname || r.author.username,
                                  label: r.author.nickname || r.author.username,
                                })
                              }
                            >
                              回复
                            </button>
                          )}
                          {(user?.id === r.author.id || isOwner) && (
                            <button onClick={() => onDeleteComment(r.id)}>删除</button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {tree.length === 0 && <div className="empty sm">还没有评论，来抢沙发吧</div>}
          </div>
        </section>
      </article>

      <aside className="post-side">
        <div className="panel author-card">
          <Link to={`/u/${post.author.username}`} className="author-link big">
            <UserAvatar user={post.author} size="lg" />
            <div>
              <div className="name">{post.author.nickname || post.author.username}</div>
              <div className="muted">@{post.author.username}</div>
            </div>
          </Link>
          {user && user.username !== post.author.username && (
            <button className={`btn ${following ? 'ghost' : 'primary'} block`} onClick={onFollow}>
              {following ? '已关注' : '+ 关注'}
            </button>
          )}
          <Link to={`/u/${post.author.username}`} className="btn ghost block">
            查看主页
          </Link>
        </div>

        {toc.length > 0 && (
          <div className="panel toc-card" style={{ marginTop: '16px' }}>
            <h4 className="toc-title">📖 文章目录</h4>
            <nav className="toc-nav">
              {toc.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`toc-item level-${item.level} ${activeTocId === item.id ? 'active' : ''}`}
                  onClick={() => scrollToHeading(item.id)}
                >
                  {item.text}
                </button>
              ))}
            </nav>
          </div>
        )}
      </aside>
    </div>
  )
}

