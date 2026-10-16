export const WELCOME_SEEN_KEY = 'blog_welcome_seen_v1'

// A memory fallback avoids redirect loops when browser storage is blocked.
export function createWelcomeHistory(getStorage = () => localStorage) {
  let seenInMemory = false
  return {
    hasSeen() {
      try { return seenInMemory || getStorage().getItem(WELCOME_SEEN_KEY) === '1' }
      catch { return seenInMemory }
    },
    markSeen() {
      seenInMemory = true
      try { getStorage().setItem(WELCOME_SEEN_KEY, '1') } catch { /* private mode/quota */ }
    },
  }
}
export const welcomeHistory = createWelcomeHistory()

export function shouldShowWelcome({ pathname, search = '', hash = '', user, loading, hasToken, seen }) {
  return pathname === '/' && !search && !hash && !user && !loading && !hasToken && !seen
}

export const AUTHOR_LINKS = Object.freeze([
  { label: 'GitHub', url: 'https://github.com/jackfeicoder', caption: '源码与开源项目' },
  { label: 'Gitee', url: 'https://gitee.com/jackfei2545', caption: '项目镜像与代码' },
  { label: 'CSDN', url: 'https://blog.csdn.net/qq_62480054', caption: '技术笔记与分享' },
])

export function authorIntroduction(bio) {
  if (typeof bio !== 'string') return ''
  let text = bio
  for (const { label, url } of AUTHOR_LINKS) {
    const escaped = url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    text = text.replace(new RegExp(`${label}\\s*[:：]?\\s*${escaped}/?(?=$|[\\s;；，,。])`, 'gi'), '')
  }
  return text.replace(/^[\s;；]+|[\s;；]+$/g, '').trim()
}
