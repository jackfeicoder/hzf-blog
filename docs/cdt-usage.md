# 访客页 CDT 公网流量

- 仅超级管理员读取 `/api/visitors/traffic`；网页只读取服务器快照，独立加载，不阻塞访客列表。
- 数据源为 `https://cdt.aliyuncs.com/` 的 `ListCdtInternetTraffic`（2021-08-13），不是 BSS 账单接口。
- 展示本月中国内地 BGP 多线公网累计流量（含免费流量），汇总所有中国内地地域的顶层 `TrafficDetails[].Traffic`。不重复累加产品细分或阶梯细分。
- 排除港澳台、海外地域和非 BGP 多线。字节除以 1024³，GB 显示保留最多五位小数。单独北京的值与全内地总和仅在只有北京使用量时相同。
- 20GB 是账号共享的中国内地免费月额度，不是单实例额度；显示总公网用量，不是剩余额度或应付费用。超过 20GB 仍展示完整数值。
- 每日北京时间 13:30 同步。该时间是用户选定的采集时间，不表示官方固定在此前更新；不承诺实时，也不沿用账单 24 小时延迟说明。
- `hzf-cdt-usage.timer` 独立运行，同一北京时间自然日默认至多读取一次；重启补执行错过任务。
- `backend/.runtime/cdt-usage.json` 原子保存安全用量与时间；不含凭证或原始响应。旧账单快照缺少数据源标记，直接隐藏，避免将账单 0 展示为流量 0。
- 读取失败保留最近成功的同数据源快照；跨月隐藏上月数据。空响应、未知结构、负数或重复地域数据均不视为 0。

## RAM 角色权限

角色信任 ECS 服务，并绑定博客 ECS 实例。自定义策略：

```json
{
  "Version": "1",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["cdt:ListCdtInternetTraffic"],
    "Resource": "*"
  }]
}
```

使用 IMDSv2 临时凭证；无需长期 AccessKey。旧 `bssapi:DescribeInstanceBill` 权限不用于此功能。

绑定角色后的首次验证：

```sh
cd /www/wwwroot/blog.120115.xyz/backend
venv/bin/python cdt_usage.py --force
```

日志只输出固定安全状态码；用量以同步时官方计数器为准，不硬编码控制台截图数值。

官方参考：

- [CDT 审计事件：公网累计用量查询](https://help.aliyun.com/zh/actiontrail/product-overview/audit-events-of-cdt)
- [CDT 只读权限策略](https://help.aliyun.com/zh/ram/developer-reference/aliyuncdtreadonlyaccess)
