import { useEffect, useRef, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { api } from '../api'

const STORAGE_KEY_PREFIX = 'blog_ai_'

export default function ChatAI() {
  const [providers, setProviders] = useState([])
  const [provider, setProvider] = useState('sensenova')
  const [model, setModel] = useState('sensenova-6.7-flash-lite')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [temperature, setTemperature] = useState(0.7)

  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: '你好！我是 AI 智能助手。目前默认开启**商汤日日新 (SenseNova)** 免费大模型，包含 `sensenova-6.7-flash-lite` 和 `deepseek-v4-flash` 官方大语言模型，无需填 Key 即可零门槛畅聊！',
    },
  ])


  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const chatEndRef = useRef(null)

  // 1. 获取后端支持的 Provider 列表
  useEffect(() => {
    api
      .getChatProviders()
      .then((res) => {
        if (res && res.providers) {
          setProviders(res.providers)
        }
      })
      .catch((err) => {
        console.error('获取 AI 提供商失败:', err)
      })

    // 读取本地保存的 Key 和配置
    const savedProvider = localStorage.getItem(STORAGE_KEY_PREFIX + 'provider') || 'sensenova'
    const savedModel = localStorage.getItem(STORAGE_KEY_PREFIX + 'model') || 'sensenova-6.7-flash-lite'
    const savedBaseUrl = localStorage.getItem(STORAGE_KEY_PREFIX + 'baseurl') || ''

    if (savedProvider) setProvider(savedProvider)
    if (savedModel) setModel(savedModel)
    if (savedBaseUrl) setBaseUrl(savedBaseUrl)

    // 如果当前为商汤免费模式，默认清空旧 key 确保直接走后端公用 key
    if (savedProvider === 'sensenova') {
      setApiKey('')
      localStorage.removeItem(STORAGE_KEY_PREFIX + 'apikey')
    } else {
      const savedKey = localStorage.getItem(STORAGE_KEY_PREFIX + 'apikey') || ''
      if (savedKey && savedKey !== 'sk-xxxx') setApiKey(savedKey)
    }
  }, [])

  // 切换 Provider 时自动切换默认 Model
  const handleProviderChange = (e) => {
    const pId = e.target.value
    setProvider(pId)
    localStorage.setItem(STORAGE_KEY_PREFIX + 'provider', pId)

    if (pId === 'sensenova') {
      setApiKey('')
      localStorage.removeItem(STORAGE_KEY_PREFIX + 'apikey')
    }

    const found = providers.find((p) => p.id === pId)
    if (found && found.models && found.models.length > 0) {
      const defaultM = found.models[0]
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
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // 发送消息（SSE 流式实时打印）
  const handleSend = async (overrideText) => {
    const textToSend = overrideText || input
    if (!textToSend.trim()) return
    if (!apiKey.trim() && provider !== 'sensenova') {
      setErrorMsg('非免费模型请先填写 API Key')
      return
    }
    setErrorMsg('')

    const userMsg = { role: 'user', content: textToSend }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    if (!overrideText) setInput('')
    setLoading(true)

    // 预先放置一个空的 assistant 消息用于流式追加内容
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }])

    const apiMessages = newMessages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-10)

    try {
      const response = await api.sendChatStream({
        provider,
        api_key: apiKey.trim(),
        base_url: baseUrl.trim() || undefined,
        model: model.trim(),
        messages: apiMessages,
        temperature: Number(temperature),
      })

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}))
        throw new Error(errJson.detail || `请求失败 (${response.status})`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data: ')) continue
          const dataStr = trimmed.slice(6).trim()
          if (dataStr === '[DONE]') break

          try {
            const parsed = JSON.parse(dataStr)
            if (parsed.error) {
              setErrorMsg(parsed.error)
              break
            }
            if (parsed.content) {
              setMessages((prev) => {
                const next = [...prev]
                const lastIdx = next.length - 1
                next[lastIdx] = {
                  ...next[lastIdx],
                  content: next[lastIdx].content + parsed.content,
                }
                return next
              })
            }
          } catch {
            /* ignore JSON parse errors */
          }
        }
      }
    } catch (err) {
      setErrorMsg(err.message || 'AI 响应失败，请检查 API Key 和网络配置')
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last && last.role === 'assistant' && !last.content) {
          return prev.slice(0, -1)
        }
        return prev
      })
    } finally {
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
          <span className="chat-config-tip">API Key 保存在浏览器本地，服务器不存储</span>
        </div>

        <div className="chat-config-grid">
          <div className="form-group">
            <label>服务提供商</label>
            <select value={provider} onChange={handleProviderChange} className="form-control">
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
              <select value={model} onChange={(e) => handleModelChange(e.target.value)} className="form-control">
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

          <div className="form-group">
            <label>API Key {provider === 'sensenova' && <span className="free-badge">🎁 默认全员免费</span>}</label>
            <div className="key-input-wrapper">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => handleKeyChange(e.target.value)}
                placeholder={provider === 'sensenova' ? '留空即使用全站免费 Key (可自填)' : '输入 sk-xxxx'}
                className="form-control"
              />

              {apiKey && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm key-toggle-btn"
                  onClick={() => handleKeyChange('')}
                  title="清空并使用全站免费 Key"
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

        {errorMsg && <div className="error-alert">{errorMsg}</div>}
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

        {/* 快捷 Prompt */}
        <div className="chat-presets">
          <button
            type="button"
            className="btn-preset"
            onClick={() => handleSend('请帮我写一篇关于 Python FastAPI 高性能后端开发的博客大纲和开篇')}
          >
            💡 生成 FastAPI 文章大纲
          </button>
          <button
            type="button"
            className="btn-preset"
            onClick={() => handleSend('请比较一下 React 与 Vue 3 在状态管理和组件开发上的异同点')}
          >
            ⚡ React vs Vue3 区别
          </button>
          <button
            type="button"
            className="btn-preset"
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
        </div>
      </div>
    </div>
  )
}
