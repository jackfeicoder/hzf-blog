export function filingForHost(hostname = '') {
  const host = hostname.toLowerCase().replace(/\.$/, '')
  return ['ithzf.xyz', 'www.ithzf.xyz', 'blog.ithzf.xyz'].includes(host)
    ? { number: '豫ICP备2026026471号', url: 'https://beian.miit.gov.cn/' }
    : null
}
