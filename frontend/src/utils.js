import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.min.css'

function escapeHtml(text = '') {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function highlightCode(code, lang) {
  const raw = code ?? ''
  try {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(raw, { language: lang, ignoreIllegals: true }).value
    }
    return hljs.highlightAuto(raw).value
  } catch {
    return escapeHtml(raw)
  }
}

const renderer = new marked.Renderer()

// 代码块：兼容 marked v9+ token 形式与旧版 (code, infostring) 形式
renderer.code = function code(tokenOrCode, infostring, escaped) {
  let text = ''
  let lang = ''

  if (tokenOrCode && typeof tokenOrCode === 'object') {
    text = tokenOrCode.text ?? ''
    lang = (tokenOrCode.lang || '').trim().split(/\s+/)[0]
  } else {
    text = tokenOrCode ?? ''
    lang = (infostring || '').trim().split(/\s+/)[0]
  }

  const language = lang && hljs.getLanguage(lang) ? lang : lang || 'plaintext'
  const highlighted = highlightCode(text, lang || undefined)
  const langLabel = lang ? escapeHtml(lang) : 'code'

  return `<div class="code-block">
  <div class="code-block-bar">
    <span class="code-lang">${langLabel}</span>
    <button type="button" class="code-copy" data-copy="1">复制</button>
  </div>
  <pre><code class="hljs language-${escapeHtml(language)}">${highlighted}</code></pre>
</div>\n`
}

// 行内 code
renderer.codespan = function codespan(tokenOrText) {
  const text =
    tokenOrText && typeof tokenOrText === 'object' ? tokenOrText.text : tokenOrText
  return `<code class="inline-code">${escapeHtml(text ?? '')}</code>`
}

// 链接：外链新窗口 + 安全 rel
renderer.link = function link(tokenOrHref, title, text) {
  let href = ''
  let titleAttr = ''
  let label = ''

  if (tokenOrHref && typeof tokenOrHref === 'object') {
    href = tokenOrHref.href || ''
    titleAttr = tokenOrHref.title || ''
    // token.tokens 已解析时用 parser；退回 raw text
    label =
      typeof this.parser?.parseInline === 'function' && tokenOrHref.tokens
        ? this.parser.parseInline(tokenOrHref.tokens)
        : escapeHtml(tokenOrHref.text || href)
  } else {
    href = tokenOrHref || ''
    titleAttr = title || ''
    label = text || href
  }

  const safeHref = String(href).trim()
  // 拦截 javascript: 等危险协议
  if (!safeHref || /^(javascript|vbscript|data):/i.test(safeHref)) {
    return label
  }

  const isExternal = /^(https?:)?\/\//i.test(safeHref)
  const titleHtml = titleAttr ? ` title="${escapeHtml(titleAttr)}"` : ''
  const extra = isExternal
    ? ' target="_blank" rel="noopener noreferrer nofollow"'
    : ''

  return `<a href="${escapeHtml(safeHref)}"${titleHtml}${extra}>${label}</a>`
}

// 图片：响应式 + 懒加载 + 失败占位
renderer.image = function image(tokenOrHref, title, text) {
  let href = ''
  let titleAttr = ''
  let alt = ''

  if (tokenOrHref && typeof tokenOrHref === 'object') {
    href = tokenOrHref.href || ''
    titleAttr = tokenOrHref.title || ''
    alt = tokenOrHref.text || ''
  } else {
    href = tokenOrHref || ''
    titleAttr = title || ''
    alt = text || ''
  }

  if (!href || /^(javascript|vbscript):/i.test(href)) {
    return alt ? `<span class="md-img-missing">${escapeHtml(alt)}</span>` : ''
  }

  const titleHtml = titleAttr ? ` title="${escapeHtml(titleAttr)}"` : ''
  const altHtml = escapeHtml(alt || '图片')
  return `<figure class="md-figure">
  <img src="${escapeHtml(href)}" alt="${altHtml}"${titleHtml} loading="lazy" decoding="async" referrerpolicy="no-referrer" />
  ${alt ? `<figcaption>${altHtml}</figcaption>` : ''}
</figure>\n`
}

// 表格包一层方便横滑
renderer.table = function table(tokenOrHeader, body) {
  // marked v12+: token object
  if (tokenOrHeader && typeof tokenOrHeader === 'object' && tokenOrHeader.header) {
    const token = tokenOrHeader
    const header = token.header
      .map((cell) => {
        const align = cell.align ? ` align="${cell.align}"` : ''
        const content =
          typeof this.parser?.parseInline === 'function'
            ? this.parser.parseInline(cell.tokens)
            : escapeHtml(cell.text)
        return `<th${align}>${content}</th>`
      })
      .join('')
    const bodyRows = token.rows
      .map((row) => {
        const tds = row
          .map((cell) => {
            const align = cell.align ? ` align="${cell.align}"` : ''
            const content =
              typeof this.parser?.parseInline === 'function'
                ? this.parser.parseInline(cell.tokens)
                : escapeHtml(cell.text)
            return `<td${align}>${content}</td>`
          })
          .join('')
        return `<tr>${tds}</tr>`
      })
      .join('')
    return `<div class="md-table-wrap"><table><thead><tr>${header}</tr></thead><tbody>${bodyRows}</tbody></table></div>\n`
  }

  // 旧签名：header html, body html
  return `<div class="md-table-wrap"><table><thead>${tokenOrHeader}</thead><tbody>${body}</tbody></table></div>\n`
}

// 标题带有 id 便于 TOC 页面锚点跳转
renderer.heading = function heading(tokenOrText, level, raw) {
  let text = ''
  let depth = level
  if (tokenOrText && typeof tokenOrText === 'object') {
    text = tokenOrText.text || ''
    depth = tokenOrText.depth || level
  } else {
    text = tokenOrText || ''
  }
  const cleanText = text.replace(/<[^>]+>/g, '').trim()
  const slug = cleanText.toLowerCase().replace(/[^\w\u4e00-\u9fa5]+/g, '-')
  const id = `heading-${slug}`
  return `<h${depth} id="${id}">${escapeHtml(cleanText)}</h${depth}>\n`
}

marked.setOptions({
  gfm: true,
  breaks: true,
  pedantic: false,
  renderer,
})

// DOMPurify：允许图片、链接常见属性，并保留代码高亮 class
const PURIFY_CONFIG = {
  USE_PROFILES: { html: true },
  ADD_TAGS: ['figure', 'figcaption'],
  ADD_ATTR: [
    'target',
    'rel',
    'class',
    'loading',
    'decoding',
    'referrerpolicy',
    'align',
    'data-copy',
    'id',
  ],
  ALLOW_DATA_ATTR: true,
}


export function renderMarkdown(md = '') {
  const raw = marked.parse(String(md || ''), { async: false })
  return DOMPurify.sanitize(raw, PURIFY_CONFIG)
}

/** 文章区挂载后绑定「复制代码」按钮（在 PostPage useEffect 里调） */
export function bindCodeCopy(root) {
  if (!root) return
  root.querySelectorAll('.code-copy').forEach((btn) => {
    if (btn.dataset.bound) return
    btn.dataset.bound = '1'
    btn.addEventListener('click', async () => {
      const block = btn.closest('.code-block')
      const code = block?.querySelector('code')?.innerText || ''
      try {
        await navigator.clipboard.writeText(code)
        const old = btn.textContent
        btn.textContent = '已复制'
        btn.classList.add('copied')
        setTimeout(() => {
          btn.textContent = old
          btn.classList.remove('copied')
        }, 1500)
      } catch {
        btn.textContent = '失败'
      }
    })
  })
}

export function timeAgo(iso) {
  if (!iso) return ''
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`
  return d.toLocaleDateString('zh-CN')
}

export function formatNum(n) {
  if (n == null) return 0
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return n
}
