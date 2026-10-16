export const MAX_IMAGE_BYTES = 2 * 1024 * 1024
export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/gif,image/webp'

export function validateImage(file) {
  if (!file || !file.size) throw new Error('请选择非空图片')
  if (file.size > MAX_IMAGE_BYTES) throw new Error('图片大小请控制在 2MB 以内')
  if (file.type && !IMAGE_ACCEPT.split(',').includes(file.type)) throw new Error('仅支持 JPG、PNG、GIF、WebP 图片')
}

export async function uploadImageFile(path, file, token) {
  validateImage(file)
  if (!token) throw new Error('请先登录再上传图片')
  const form = new FormData()
  form.append('file', file)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 60_000)
  try {
    const response = await fetch(path, { method: 'POST', headers: { Authorization: `Bearer ${token}` },
      body: form, signal: controller.signal })
    const body = await response.json().catch(() => null)
    if (!response.ok || !body?.url) {
      const error = new Error(typeof body?.detail === 'string' ? body.detail : `图片上传失败 (${response.status})，请稍后再试`)
      error.status = response.status
      throw error
    }
    return body
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('图片上传超时，请稍后再试')
    throw error
  } finally { clearTimeout(timer) }
}

export function imageDimensions(url) {
  const match = /#cb-size=(\d+)x(\d+)$/.exec(url || '')
  if (!match) return null
  const width = Number(match[1]), height = Number(match[2])
  return width > 0 && height > 0 && width <= 20000 && height <= 20000 ? { width, height } : null
}

export function imageMarkdown(file, result) {
  const label = (file.name || '图片').replace(/[\[\]\\\r\n]/g, ' ')
  const dimensions = result.width && result.height ? `#cb-size=${result.width}x${result.height}` : ''
  return `\n![${label}](${result.url}${dimensions})\n`
}
