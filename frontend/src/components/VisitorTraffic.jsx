import { useEffect, useState } from 'react'
import { api } from '../api'
import './visitor-traffic.css'

const messages = {
  credentials_missing: '尚未配置账单读取权限',
  permission_denied: '账单查询权限不足，等待管理员配置',
  unsupported_bill_data: '账单格式待核对，暂不展示用量',
  data_unavailable: '尚未取得完整的本月账单',
}

export default function VisitorTraffic() {
  const [data, setData] = useState(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    api.visitorTraffic().then(value => { if (active) setData(value) }).catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [])
  const used = typeof data?.used_gb === 'number' && Number.isFinite(data.used_gb) ? data.used_gb : null
  const amount = used === null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(used)
  const caption = failed ? '读取失败，下次打开页面重试' : !data ? '正在读取用量快照…' : used === null
    ? messages[data.error_code] || '等待首次账单同步'
    : data.status === 'stale' ? '同步暂未完成，显示最近成功的账单数据' : '中国内地账号共享额度 · 账单约延迟24小时'
  return <section className="card visitor-traffic" aria-label="本月公网流量">
    <div className="visitor-traffic-title"><span aria-hidden="true">↗</span><div>
      <strong>本月已用 <b>{amount}</b> / {data?.quota_gb ?? 20}GB</strong>
      <small>{caption}</small>
    </div></div>
    <div className="visitor-traffic-detail">
      {used !== null && <progress aria-label="本月免费流量使用比例" value={Math.min(used, data.quota_gb)} max={data.quota_gb} />}
      <small>每日13:30同步 · 北京时间</small>
      {data?.updated_at && <small>最近同步：{new Date(data.updated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</small>}
    </div>
  </section>
}
