import { useEffect, useRef, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { api } from '../api'
import { useAuth } from '../AuthContext'
import { availableModel, DEFAULT_CHAT_MODEL, readChatEvents } from '../chat/config'

const STORAGE_KEY_PREFIX = 'blog_ai_'

export default function ChatAI() {
  const { user } = useAuth()
  const [providers, setProviders] = useState([])
  const [provider, setProvider] = useState('sensenova')
  const [model, setModel] = useState(DEFAULT_CHAT_MODEL)
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [temperature, setTemperature] = useState(0.7)
  const [reasoning, setReasoning] = useState('none')
  const [modelNotice, setModelNotice] = useState('')

  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: '你好！我是 AI 智能助手。选择模型提供商后即可开始对话；请填写自己的 API Key，或使用站点管理员已配置的 SenseNova 服务。模型可用性和额度以提供商为准。',
    },
  ])


  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const chatEndRef = useRef(null)
  const requestRef = useRef(null)
  useEffect(() => () => requestRef.current?.abort(), [])

  // 1. 获取后端支持的 Provider 列表
  useEffect(() => {
    let active = true
    api
      .getChatProviders()
      .then((res) => {
        if (active && res && res.providers) {
          setProviders(res.providers)
          const nextModel = availableModel(savedModel, res.providers.find(p => p.id === savedProvider))
          setModel(nextModel)
          localStorage.setItem(STORAGE_KEY_PREFIX + 'model', nextModel)
          if (nextModel !== savedModel) setModelNotice(`原模型已更新，已为你选择 ${nextModel}`)
        }
      })
      .catch((err) => {
        console.error('获取 AI 提供商失败:', err)
      })

    // 读取本地保存的 Key 和配置
    const savedProvider = localStorage.getItem(STORAGE_KEY_PREFIX + 'provider') || 'sensenova'
    const savedModel = localStorage.getItem(STORAGE_KEY_PREFIX + 'model') || DEFAULT_CHAT_MODEL
    const savedBaseUrl = localStorage.getItem(STORAGE_KEY_PREFIX + 'baseurl') || ''

    if (savedProvider) setProvider(savedProvider)
    if (savedModel) setModel(savedModel)
    if (savedBaseUrl) setBaseUrl(savedBaseUrl)

    const savedKey = localStorage.getItem(STORAGE_KEY_PREFIX + 'apikey') || ''
    if (savedKey && savedKey !== 'sk-xxxx') setApiKey(savedKey)
    return () => { active = false }
  }, [])

  // 切换 Provider 时自动切换默认 Model
  const handleProviderChange = (e) => {
    const pId = e.target.value
    setModelNotice('')
    setProvider(pId)
    localStorage.setItem(STORAGE_KEY_PREFIX + 'provider', pId)

    const found = providers.find((p) => p.id === pId)
    if (found && found.models && found.models.length > 0) {
      const defaultM = availableModel('', found)
      setModel(defaultM)
      localStorage.setItem(STORAGE_KEY_PREFIX + 'model', defaultM)
    } else {
      setModel('')
    }
  }


  const handleKeyChange = (val) => {
    setApiKey(val)
    localStorage.setItem(STORAGE_KEY_PREFIX + 'apikey', val)
  }

  const handleModelChange = (val) => {
    setModel(val)
    localStorage.setItem(STORAGE_KEY_PREFIX + 'model', val)
  }

  const handleBaseUrlChange = (val) => {
    setBaseUrl(val)
    localStorage.setItem(STORAGE_KEY_PREFIX + 'baseurl', val)
  }

  // 滚动到底部
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: loading ? 'auto' : 'smooth', block: 'nearest' })
  }, [messages, loading])

  // 发送消息（SSE 流式实时打印）
  const handleSend = async (overrideText) => {
    const textToSend = overrideText || input
    if (loading || requestRef.current || !textToSend.trim()) return
    if (!model.trim()) { setErrorMsg('请先选择可用模型'); return }
    if (!apiKey.trim() && provider !== 'sensenova') {
      setErrorMsg('请先填写 API Key')
      return
    }
    if (!apiKey.trim() && provider === 'sensenova' && !user) {
      setErrorMsg('使用站点模型请先登录博客，或填写自己的 API Key')
      return
    }
    setErrorMsg('')

    const userMsg = { role: 'user', content: textToSend }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    if (!overrideText) setInput('')
    setLoading(true)
    const controller = new AbortController()
    requestRef.current = controller

    // 预先放置一个空的 assistant 消息用于流式追加内容
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }])

    const apiMessages = newMessages.slice(1)
      .filter((m) => m.content && (m.role === 'user' || m.role === 'assistant'))
      .slice(-10)
    // Never send the local greeting as an initial assistant message.
    while (apiMessages[0]?.role === 'assistant') apiMessages.shift()

    try {
      const response = await api.sendChatStream({
        provider,
        api_key: apiKey.trim(),
        base_url: provider === 'custom' ? baseUrl.trim() || undefined : undefined,
        model: model.trim(),
        messages: apiMessages,
        temperature: Number(temperature),
        reasoning_effort: reasoning,
      }, controller.signal)

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}))
        throw new Error(errJson.detail || `请求失败 (${response.status})`)
      }

      await readChatEvents(response, parsed => {
        if (parsed.model && parsed.model !== model) {
          setModel(parsed.model)
          localStorage.setItem(STORAGE_KEY_PREFIX + 'model', parsed.model)
        }
        if (parsed.content) setMessages(prev => {
          const next = [...prev], last = next.length - 1
          next[last] = {...next[last], content: next[last].content + parsed.content}
          return next
        })
      })
    } catch (err) {
      setErrorMsg(err.name === 'AbortError' ? '' : err.message || 'AI 响应失败，请检查 API Key 和网络配置')
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last && last.role === 'assistant' && !last.content) {
          return prev.slice(0, -1)
        }
        return prev
      })
    } finally {
      requestRef.current = null
      setLoading(false)
    }
  }



  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const renderMarkdown = (content) => {
    try {
      const rawHtml = marked.parse(content || '')
      const cleanHtml = DOMPurify.sanitize(rawHtml)
      return { __html: cleanHtml }
    } catch {
      return { __html: content }
    }
  }

  const curProviderObj = providers.find((p) => p.id === provider)

  return (
    <div className="chat-ai-container">
      {/* 顶部配置面板 */}
      <div className="card chat-config-card">
        <div className="chat-config-header">
          <h2>🤖 AI 智能助手</h2>
          <span className="chat-config-tip">个人 Key 保存在本浏览器；站点 Key 仅保存在服务器，登录后可用</span>
        </div>

        <div className="chat-config-grid">
          <div className="form-group">
            <label>服务提供商</label>
            <select value={provider} disabled={loading || !providers.length} onChange={handleProviderChange} className="form-control">
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>模型选择</label>
            {curProviderObj && curProviderObj.models && curProviderObj.models.length > 0 ? (
              <select value={model} disabled={loading} onChange={(e) => handleModelChange(e.target.value)} className="form-control">
                {curProviderObj.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={model}
                onChange={(e) => handleModelChange(e.target.value)}
                placeholder="例如 gpt-4o-mini / deepseek-chat"
                className="form-control"
              />
            )}
          </div>

          {provider === 'sensenova' && <div className="form-group">
            <label>回答模式</label>
            <select value={reasoning} disabled={loading} onChange={e => setReasoning(e.target.value)} className="form-control">
              <option value="none">快速回答（默认）</option>
              <option value="high">深度思考（等待更久、消耗更多额度）</option>
            </select>
          </div>}

          <div className="form-group">
            <label>API Key {provider === 'sensenova' && providers.find(p => p.id === provider)?.is_free && <span className="free-badge">站点已配置</span>}</label>
            <div className="key-input-wrapper">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => handleKeyChange(e.target.value)}
                placeholder={provider === 'sensenova' ? '填写自己的 Key，或使用管理员已配置的 Key' : '输入 API Key'}
                className="form-control"
              />

              {apiKey && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm key-toggle-btn"
                  onClick={() => handleKeyChange('')}
                  title="清空当前 Key"
                >
                  清空Key
                </button>
              )}
              <button
                type="button"
                className="btn btn-secondary btn-sm key-toggle-btn"
                onClick={() => setShowKey(!showKey)}
              >
                {showKey ? '隐藏' : '显示'}
              </button>

            </div>
          </div>

          {provider === 'custom' && (
            <div className="form-group full-width">
              <label>Custom Base URL</label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => handleBaseUrlChange(e.target.value)}
                placeholder="例如 http://127.0.0.1:3000 或 https://api.openai.com"
                className="form-control"
              />
            </div>
          )}
        </div>

        {modelNotice && <p className="chat-config-tip" role="status">{modelNotice}</p>}
        {provider === 'sensenova' && <p className="chat-config-tip">模型列表定期同步官方；可用性及剩余额度以商汤套餐为准。站点调用每人每分钟最多 10 次。</p>}
      </div>

      {/* 聊天对话区域 */}
      <div className="card chat-box-card">
        <div className="chat-messages-list">
          {messages.map((m, idx) => (
            <div key={idx} className={`chat-message-row ${m.role}`}>
              <div className="chat-avatar">{m.role === 'user' ? '👤' : '🤖'}</div>
              {m.role === 'assistant' && !m.content ? (
                <div className="chat-bubble loading-bubble">
                  <span className="dot-pulse">AI 正在思考中...</span>
                </div>
              ) : (
                <div className="chat-bubble">
                  <div
                    className="markdown-body"
                    dangerouslySetInnerHTML={renderMarkdown(m.content)}
                  />
                </div>
              )}
            </div>
          ))}
          <div ref={chatEndRef} />

        </div>

        {errorMsg && <div className="error-alert" role="alert">{errorMsg}</div>}
        {/* 快捷 Prompt */}
        <div className="chat-presets">
          <button
            type="button"
            className="btn-preset"
            disabled={loading}
            onClick={() => handleSend('请帮我写一篇关于 Python FastAPI 高性能后端开发的博客大纲和开篇')}
          >
            💡 生成 FastAPI 文章大纲
          </button>
          <button
            type="button"
            className="btn-preset"
            disabled={loading}
            onClick={() => handleSend('请比较一下 React 与 Vue 3 在状态管理和组件开发上的异同点')}
          >
            ⚡ React vs Vue3 区别
          </button>
          <button
            type="button"
            className="btn-preset"
            disabled={loading}
            onClick={() => handleSend('请帮我排查并重构一段代码，使其性能更好、结构更清晰')}
          >
            🛠️ 代码优化排查
          </button>
        </div>

        {/* 输入框与发送 */}
        <div className="chat-input-area">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入您的问题... (Enter 发送，Shift+Enter 换行)"
            rows={2}
            className="form-control chat-textarea"
          />
          <button
            type="button"
            disabled={loading || !input.trim()}
            onClick={() => handleSend()}
            className="btn btn-primary btn-send"
          >
            {loading ? '发送中...' : '发送'}
          </button>
          {loading && <button type="button" className="btn" onClick={() => requestRef.current?.abort()}>停止生成</button>}
        </div>
      </div>
    </div>
  )
}
