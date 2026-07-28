import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../AuthContext'
import PostCard from '../components/PostCard'
import { avatarText } from '../components/Layout'
import { formatNum } from '../utils'

export default function Profile() {
  const { username } = useParams()
  const { user } = useAuth()
  const [profile, setProfile] = useState(null)
  const [tab, setTab] = useState('posts') // posts | favorites
  const [posts, setPosts] = useState([])
  const [total, setTotal] = useState(0)
  const [err, setErr] = useState('')

  const loadProfile = async () => {
    const p = await api.getUser(username)
    setProfile(p)
  }

  const loadList = async () => {
    if (tab === 'posts') {
      const data = await api.listPosts({ author: username, page: 1, page_size: 20 })
      setPosts(data.items)
      setTotal(data.total)
    } else {
      const data = await api.userFavorites(username, 1)
      setPosts(data.items)
      setTotal(data.total)
    }
  }

  useEffect(() => {
    setErr('')
    loadProfile().catch((e) => setErr(e.message))
  }, [username])

  useEffect(() => {
    if (!profile) return
    loadList().catch((e) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, tab])

  if (err) return <div className="container empty">{err}</div>
  if (!profile) return <div className="container empty">加载中...</div>

  const isMe = user?.username === profile.username

  const onFollow = async () => {
    if (!user) return (window.location.href = '/login')
    const r = await api.followUser(profile.username)
    setProfile({ ...profile, is_following: r.active, follower_count: r.count })
  }

  return (
    <div className="container profile-page">
      <div className="panel profile-header">
        <span className="avatar xl">{avatarText(profile.nickname || profile.username)}</span>
        <div className="profile-info">
          <h1>
            {profile.nickname || profile.username}
            {profile.is_admin && <span className="badge">管理员</span>}
          </h1>
          <div className="muted">@{profile.username}</div>
          <p className="bio">{profile.bio || '这个人很懒，还没有写简介'}</p>
          <div className="profile-stats">
            <span>
              <b>{profile.post_count}</b> 文章
            </span>
            <span>
              <b>{profile.follower_count}</b> 粉丝
            </span>
            <span>
              <b>{profile.following_count}</b> 关注
            </span>
            <span>
              <b>{formatNum(profile.total_likes)}</b> 获赞
            </span>
            <span>
              <b>{formatNum(profile.total_views)}</b> 阅读
            </span>
          </div>
        </div>
        <div className="profile-actions">
          {isMe ? (
            <Link to="/write" className="btn primary">
              写文章
            </Link>
          ) : (
            <button className={`btn ${profile.is_following ? 'ghost' : 'primary'}`} onClick={onFollow}>
              {profile.is_following ? '已关注' : '+ 关注'}
            </button>
          )}
        </div>
      </div>

      <div className="sort-tabs profile-tabs">
        <button className={tab === 'posts' ? 'active' : ''} onClick={() => setTab('posts')}>
          文章 {total > 0 && tab === 'posts' ? `(${total})` : ''}
        </button>
        <button className={tab === 'favorites' ? 'active' : ''} onClick={() => setTab('favorites')}>
          收藏
        </button>
      </div>

      <div className="profile-feed">
        {posts.length === 0 ? (
          <div className="empty">{tab === 'posts' ? '还没有发布文章' : '还没有收藏'}</div>
        ) : (
          posts.map((p) => <PostCard key={p.id} post={p} />)
        )}
      </div>
    </div>
  )
}
