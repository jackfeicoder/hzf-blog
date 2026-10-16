export const DEFAULT_CHAT_MODEL = 'sensenova-6.8-flash-lite'

export function availableModel(saved, provider) {
  if (!provider || provider.id === 'custom') return saved || ''
  const models = provider.models || []
  if (models.includes(saved)) return saved
  return models.includes(provider.default_model) ? provider.default_model : (models[0] || '')
}

// OpenAI-compatible SSE: chunk boundaries are not event/UTF-8 boundaries.
export async function readChatEvents(response, onEvent) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = '', done = false
  function consume(block) {
    const data = block.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart()).join('\n').trim()
    if (!data) return
    if (data === '[DONE]') { done = true; return }
    const parsed = JSON.parse(data)
    if (parsed.error) throw new Error(parsed.error)
    onEvent(parsed)
  }
  try {
    while (!done) {
      const chunk = await reader.read()
      buffer += decoder.decode(chunk.value, { stream: !chunk.done })
      buffer = buffer.replace(/\r\n/g, '\n')
      let boundary
      while (!done && (boundary = buffer.indexOf('\n\n')) >= 0) {
        consume(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
      }
      if (chunk.done) { if (!done && buffer.trim()) consume(buffer); break }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
