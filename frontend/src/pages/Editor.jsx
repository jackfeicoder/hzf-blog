import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../AuthContext'
import { renderMarkdown } from '../utils'

export default function Editor() {
  const { id } = useParams()
  const isEdit = Boolean(id)
  const { user, loading: authLoading } = useAuth()
  const nav = useNavigate()

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [summary, setSummary] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [tags, setTags] = useState('')
  const [published, setPublished] = useState(true)
  const [categories, setCategories] = useState([])
  const [preview, setPreview] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!authLoading && !user) nav('/login')
  }, [user, authLoading, nav])

  useEffect(() => {
    api.listCategories().then(setCategories).catch(() => {})
  }, [])

  useEffect(() => {
    if (!isEdit) return
    api
      .getPost(id)
      .then((p) => {
        setTitle(p.title)
        setContent(p.content)
        setSummary(p.summary || '')
        setCategoryId(p.category?.id || '')
        setTags((p.tags || []).map((t) => t.name).join(', '))
        setPublished(p.published)
      })
      .catch((e) => setErr(e.message))
  }, [id, isEdit])

  const html = useMemo(() => renderMarkdown(content), [content])

  const onSubmit = async (e) => {
    e.preventDefault()
    if (!title.trim() || !content.trim()) {
      setErr('标题和正文不能为空')
      return
    }
    setBusy(true)
    setErr('')
    const payload = {
      title: title.trim(),
      content,
      summary: summary.trim(),
      category_id: categoryId ? Number(categoryId) : null,
      tags: tags
        .split(/[,，\s]+/)
        .map((t) => t.trim())
        .filter(Boolean),
      published,
    }
    try {
      const post = isEdit ? await api.updatePost(id, payload) : await api.createPost(payload)
      nav(`/post/${post.id}`)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (authLoading) return <div className="container empty">加载中...</div>

  return (
    <div className="container editor-page">
      <form className="panel editor-form" onSubmit={onSubmit}>
        <div className="editor-top">
          <h2>{isEdit ? '编辑文章' : '写文章'}</h2>
          <div className="editor-actions">
            <button type="button" className="btn ghost" onClick={() => setPreview((v) => !v)}>
              {preview ? '编辑' : '预览'}
            </button>
            <label className="check">
              <input type="checkbox" checked={published} onChange={(e) => setPublished(e.target.checked)} />
              发布
            </label>
            <button className="btn primary" disabled={busy}>
              {busy ? '保存中...' : isEdit ? '更新' : '发布文章'}
            </button>
          </div>
        </div>

        {err && <div className="alert">{err}</div>}

        <input
          className="title-input"
          placeholder="输入文章标题..."
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />

        <div className="editor-meta-row">
          <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="">选择分类</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input
            placeholder="标签，逗号分隔，如 React, FastAPI"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
          />
        </div>

        <input
          placeholder="摘要（可选，默认截取正文前 150 字）"
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
        />

        {preview ? (
          <div className="markdown-body editor-preview" dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <textarea
            className="md-input"
            rows={22}
            placeholder="用 Markdown 写正文..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        )}
      </form>
    </div>
  )
}
