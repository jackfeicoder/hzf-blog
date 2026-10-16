import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { api, getToken } from '../api'
import { UserAvatar } from '../components/Layout'
import BioText from '../components/BioText'
import { AUTHOR_LINKS, authorIntroduction, welcomeHistory } from '../welcome/policy'
import './welcome.css'

const features = [
  { icon: 'pen', title: '写下你的技术故事', label: '文章创作', text: '用 Markdown 记录笔记、项目实践与思考。代码高亮、图片和草稿，让知识慢慢沉淀。' },
  { icon: 'chat', title: '让交流发生', label: '评论 · 点赞 · 收藏', text: '在评论里交换想法，为有帮助的内容点赞，把值得再读的文章收藏起来。' },
  { icon: 'people', title: '找到一起成长的人', label: '关注 · 个人主页', text: '关注喜欢的作者，在个人主页展示自己，也看看彼此正在学习和分享什么。' },
  { icon: 'chart', title: '发现值得读的内容', label: '搜索 · 排行榜', text: '按分类和关键词找文章，从热门文章与作者榜发现更多好内容。' },
  { icon: 'check', title: '把学习变成日常', label: '学习打卡', text: '每天 5 道 Java 八股、2 道 Hot100，加一点项目学习。从 HelloAgent 到 paicli、RAG，完成一轮再复习。' },
  { icon: 'music', title: '给专注配一点旋律', label: '在线音乐', text: '搜索歌曲、看歌词、收藏喜欢的音乐；播放队列和音量控制，让听歌自然融入阅读。' },
  { icon: 'play', title: '忙完，也放松一下', label: '看视频', text: '整理实用的视频网站入口，一键前往对应网站。这里是链接导航，不托管影视内容。' },
  { icon: 'spark', title: '留一点空间给好奇心', label: '问 AI · 全站主题', text: '带着问题与 AI 交流，在统一的背景、配色和轻量特效里，舒服地阅读与探索。' },
]

function FeatureIcon({ name }) {
  const paths = {
    pen: <><path d="m14 4 6 6M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15l-1 5Z" /></>,
    chat: <><path d="M20 11a8 8 0 0 1-8 8H5l-3 3v-11a8 8 0 0 1 16-5" /><path d="M7 10h7M7 14h5" /></>,
    people: <><circle cx="9" cy="8" r="3" /><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M21 20v-2a6 6 0 0 0-4-5" /></>,
    chart: <><path d="M4 4v16h16M8 15v-4M13 15V8M18 15V5" /></>,
    check: <><rect x="4" y="5" width="16" height="16" rx="3" /><path d="M8 3v4M16 3v4m-8 7 3 3 5-6" /></>,
    music: <><path d="M9 18V5l11-2v13M9 8l11-2" /><ellipse cx="6" cy="18" rx="3" ry="2" /><ellipse cx="17" cy="16" rx="3" ry="2" /></>,
    play: <><rect x="3" y="4" width="18" height="16" rx="4" /><path d="m10 8 6 4-6 4Z" /></>,
    spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" /></>,
  }
  return <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

export default function Welcome({ introductory = false }) {
  const { user, loading } = useAuth()
  const [author, setAuthor] = useState(null)
  const [authorFailed, setAuthorFailed] = useState(false)
  useEffect(() => {
    let active = true
    api.getUser('administrator').then(value => { if (active) setAuthor(value) })
      .catch(() => { if (active) setAuthorFailed(true) })
    return () => { active = false }
  }, [])
  if (introductory && (user || getToken())) return <Navigate to="/" replace />
  if (introductory && loading) return <div className="container empty">正在确认登录状态…</div>
  const intro = authorIntroduction(author?.bio)
  const entry = user ? '/' : '/register'
  const acknowledge = () => welcomeHistory.markSeen()
  return <div className="container welcome-page">
    <section className="panel welcome-hero" aria-labelledby="welcome-title">
      <div className="welcome-copy">
        <span className="welcome-eyebrow">A LITTLE SPACE FOR BIG IDEAS</span>
        <div className="welcome-kicker"><span />记录 · 分享 · 一起成长</div>
        <h1 id="welcome-title">在这里，<br />把好奇心<span>写成日常。</span></h1>
        <p className="welcome-lead">欢迎来到 CodeBlog。这里是一份持续生长的技术笔记，也是一处可以交流、学习，偶尔听听歌的小天地。</p>
        <div className="welcome-cta">
          <Link className="btn primary" to={entry} onClick={acknowledge}>进入博客 <span aria-hidden="true">↗</span></Link>
          {!user && <Link className="btn ghost" to="/login" onClick={acknowledge}>已有账号，去登录</Link>}
        </div>
        <p className="welcome-entry-note">{user ? '继续阅读、创作和学习。' : '点击“进入博客”前往注册，注册成功后即可开始使用。'}</p>
        <div className="welcome-tags"><span>分享所学</span><span>遇见同频的人</span><span>保持一点热爱</span></div>
      </div>
      <aside className="welcome-author" aria-labelledby="welcome-author-title">
        <div className="welcome-author-top"><span className="welcome-eyebrow">MEET THE AUTHOR</span><span className="welcome-author-badge">作者</span></div>
        <UserAvatar user={author || { nickname:'管理员' }} size="xl" />
        <h2 id="welcome-author-title">很高兴在这里遇见你</h2>
        <p className="welcome-author-bio"><BioText text={intro || '热爱编程与技术分享，在这里记录学习、实践与成长。'} /></p>
        {authorFailed && <small className="welcome-author-note">简介暂未加载，仍可通过下方链接了解作者。</small>}
        <Link to="/u/administrator" className="welcome-profile-link">查看作者主页 <span aria-hidden="true">→</span></Link>
        <div className="welcome-socials" aria-label="作者的其他平台">
          {AUTHOR_LINKS.map(link => <a key={link.label} href={link.url} target="_blank" rel="noopener noreferrer">
            <div><strong>{link.label}</strong><small>{link.caption}</small></div><span aria-hidden="true">↗</span>
          </a>)}
        </div>
      </aside>
    </section>
    <section className="welcome-features" aria-labelledby="welcome-features-title">
      <div className="welcome-section-heading"><div><span className="welcome-eyebrow">MORE THAN A BLOG</span><h2 id="welcome-features-title">写作之外，还有这些小美好。</h2></div><p>从一篇文章开始，让知识、交流和生活连接起来。</p></div>
      <div className="welcome-feature-grid">
        {features.map(feature => <article key={feature.icon} className="panel welcome-feature">
          <div className="welcome-feature-top"><span className="welcome-feature-icon"><FeatureIcon name={feature.icon} /></span><small>{feature.label}</small></div>
          <h3>{feature.title}</h3><p>{feature.text}</p>
        </article>)}
      </div>
    </section>
    <section className="panel welcome-end"><div><span className="welcome-eyebrow">YOUR NEXT CHAPTER</span><h2>下一篇故事，也许就来自你。</h2><p>留下一点思考，收藏一点灵感。欢迎加入。</p></div>
      <Link className="btn primary" to={entry} onClick={acknowledge}>进入博客 <span aria-hidden="true">→</span></Link>
    </section>
  </div>
}
