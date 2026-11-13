# 访客页CDT流量用量

- 仅站点超级管理员可读取 `/api/visitors/traffic`，页面独立加载小卡片，其他访客数据不等待该请求。
- 展示“本月已用 x / 20GB”。20GB是中国内地账号共享月额度，不是单实例独享；超额仍显示实际用量，进度条最多100%。
- 使用BSS `DescribeInstanceBill`，按月、计费项查询CDT，保留零费用行并处理全部分页，汇总中国内地公网GB用量，排除跨地域及非中国内地用量。
- 数据是已出账用量，不含未结算流量，约延迟24小时。当月账单可能调整，不作实时计费或精确防超额依据。
- 官方未公布固定每天更新时间，因此采用用户确认的每天北京时间13:30同步，并非声称固定在官方更新后半小时。
- 由 `hzf-cdt-usage.timer` 调用独立的一次性服务，不依赖网页访问或博客进程。重启后补执行错过的定时任务，同一北京时间自然日默认至多同步一次。
- 可在角色绑定后执行一次 `systemctl start hzf-cdt-usage.service`；如当天已失败尝试，需要管理员显式执行后端虚拟环境Python的 `cdt_usage.py --force` 完成首次验证。
- 快照位置默认 `backend/.runtime/cdt-usage.json`，原子替换，只有安全用量与时间字段；无密钥、原始账单、账号ID和实例IP。网页请求不调用账单API或元数据服务。
- 查询失败保留最近成功快照，显示“同步暂未完成”；跨月隐藏上月用量并等待本月结果。空账单、未知单位或无法识别的地域不按0处理。
- 不改账号、账单计费方式或CDT配置；API Action固定为只读 `DescribeInstanceBill`，权限不足不会尝试提权。

## 最小RAM角色权限

在RAM创建自定义策略，绑定给可信实体为“阿里云服务→云服务器ECS”的普通服务角色，再在ECS实例的“授予/修改RAM角色”中绑定。

```json
{
  "Version": "1",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bssapi:DescribeInstanceBill"],
    "Resource": ["*"],
    "Condition": {"StringEquals": {"bssapi:ProductCode": "cdt"}}
  }]
}
```

优先使用ECS IMDSv2获取临时凭证，不创建长期AccessKey。备用配置支持仅服务器定时服务可读取的 `/root/.config/hzf-blog/cdt.env` 中 `CDT_ACCESS_KEY_ID`、`CDT_ACCESS_KEY_SECRET`、可选 `CDT_SECURITY_TOKEN`，该文件不进入仓库。不得给浏览器或公开接口返回凭证。

官方文档：

- [DescribeInstanceBill与延迟说明](https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-describeinstancebill)
- [CDT账单与共享额度](https://help.aliyun.com/zh/cdt/query-bills)
- [ECS绑定RAM角色](https://help.aliyun.com/zh/ecs/user-guide/attach-an-instance-ram-role-to-an-ecs-instance)
