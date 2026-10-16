import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import { IMAGE_ACCEPT, validateImage } from '../imageAssets'
import { useAppearance } from './AppearanceContext'
import { DEFAULT_APPEARANCE } from './settings'

function Choices({ label, field, items, settings, update }) {
  return <fieldset className="appearance-section"><legend>{label}</legend><div className={`appearance-choices ${field}`}>
    {items.map(([value, text, color]) => <button key={value} type="button" aria-pressed={settings[field] === value}
      className={`appearance-choice ${value}`} onClick={() => update({ [field]: value })}>
      {color && <span className="appearance-swatch" style={{ background: color }} aria-hidden="true" />}{text}
    </button>)}
  </div></fieldset>
}

export default function AppearanceSettings({ onClose }) {
  const { settings, status, error: saveError, update, publish, discard, dirty } = useAppearance()
  const dialog = useRef(null), input = useRef(null), mounted = useRef(true)
  const [uploading, setUploading] = useState(false), [error, setError] = useState('')
  useEffect(() => {
    mounted.current = true
    const previous = document.activeElement
    dialog.current.showModal()
    return () => { mounted.current = false; dialog.current?.close(); previous?.focus?.() }
  }, [])
  const upload = async e => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      validateImage(file)
      setError(''); setUploading(true)
      const result = await api.uploadImage(file)
      if (mounted.current) update({ background: 'custom', background_url: result.url })
    } catch (err) { if (mounted.current) setError(err.message || '上传失败，请重试') }
    finally { if (mounted.current) setUploading(false) }
  }
  const statuses = { saved: '全站样式已同步', saving: '正在应用到全站…', draft: '预览中，尚未应用到全站', loading: '正在读取全站样式…', offline: '网络暂时异常，正在使用上次全站样式', error: '发布失败，其他用户的样式未改变' }
  return createPortal(<dialog ref={dialog} className="appearance-dialog" aria-labelledby="appearance-title"
    onCancel={e => { e.preventDefault(); onClose() }} onClick={e => { if (e.target === dialog.current) {
      const r = dialog.current.getBoundingClientRect()
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose()
    } }}>
    <div className="appearance-dialog-effects" aria-hidden="true" />
    <header className="appearance-heading"><div><span className="appearance-eyebrow">SITE APPEARANCE</span>
      <h2 id="appearance-title">全站外观与特效</h2><p>仅管理员可编辑。应用后，所有用户和访客使用同一套样式。</p></div>
      <button autoFocus type="button" className="icon-btn" aria-label="关闭外观设置" onClick={onClose}>✕</button></header>
    <div className="appearance-content">
      <fieldset className="appearance-section appearance-controls" disabled={status === 'saving' || uploading}>
      <Choices label="明暗模式" field="theme" items={[[ 'light', '浅色' ],[ 'dark', '深色' ]]} {...{ settings, update }} />
      <Choices label="主题配色" field="palette" items={[[ 'warm', '暖橙', '#ff5733' ],[ 'ocean', '海蓝', '#2876cf' ],[ 'forest', '森林', '#23815a' ],[ 'violet', '紫罗兰', '#8653cc' ]]} {...{ settings, update }} />
      <fieldset className="appearance-section"><legend>毛玻璃透明度</legend>
        <div className="appearance-slider"><input id="glass-transparency" type="range" min="0" max="80" step="1"
          aria-label="毛玻璃透明度" value={settings.glass_transparency} onChange={e => update({ glass_transparency: Number(e.target.value) })} />
          <output htmlFor="glass-transparency">{settings.glass_transparency}%</output></div>
        <p className="appearance-help">0% 为不透明，数值越大越通透。调整立即预览，不增加全屏模糊的渲染负担。</p>
      </fieldset>
      <Choices label="页面背景" field="background" items={[[ 'aurora', '柔光' ],[ 'dawn', '晨曦' ],[ 'none', '简洁' ], ...(settings.background_url ? [[ 'custom', '我的图片' ]] : [])]} {...{ settings, update }} />
      <div className="appearance-upload">
        <input ref={input} type="file" accept={IMAGE_ACCEPT} onChange={upload} hidden />
        <button type="button" className="btn ghost" disabled={uploading} onClick={() => input.current.click()}>{uploading ? '图片上传中…' : '上传全站背景'}</button>
        {settings.background_url && <button type="button" className="btn-link" onClick={() => update({ background: 'none', background_url: '' })}>移除背景</button>}
        <p>PNG / JPG / WebP / GIF，单张不超过 2MB。应用后图片公开展示，异步加载并可缓存 30 天。请勿上传敏感图片。</p>
        {error && <p role="alert" className="appearance-error">{error}</p>}
      </div>
      <Choices label="鼠标样式" field="cursor" items={[[ 'system', '系统默认' ],[ 'accent', '柔和彩色' ]]} {...{ settings, update }} />
      <Choices label="点击特效" field="click_effect" items={[[ 'ripple', '涟漪' ],[ 'stars', '星光' ],[ 'none', '关闭' ]]} {...{ settings, update }} />
      <label className="appearance-motion"><input type="checkbox" checked={settings.motion} onChange={e => update({ motion: e.target.checked })} />
        <span>启用轻量过渡动画<small>系统开启“减少动态效果”时，动画和点击特效自动暂停。</small></span></label>
      </fieldset>
      {saveError && <p role="alert" className="appearance-error">{saveError}</p>}
    </div>
    <footer className="appearance-foot"><div role="status">{statuses[status]}
      </div><div className="appearance-actions">
      <button type="button" className="btn-link" disabled={status === 'saving' || uploading} onClick={() => update(DEFAULT_APPEARANCE)}>恢复默认</button>
      {dirty && <button type="button" className="btn ghost sm" disabled={status === 'saving' || uploading} onClick={discard}>撤销预览</button>}
      <button type="button" className="btn primary sm" disabled={!dirty || status === 'saving' || uploading} onClick={publish}>{status === 'saving' ? '应用中…' : '应用到全站'}</button>
      </div></footer>
  </dialog>, document.body)
}
