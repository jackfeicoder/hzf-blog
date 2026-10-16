# 商汤聊天接入

官方文档：https://platform.sensenova.cn/docs

使用 `https://token.sensenova.cn/v1/chat/completions` 的 OpenAI 兼容接口，支持普通响应与 SSE 流式响应。2026-10-03 查询官方 `/v1/models`：旧 `sensenova-6.7-flash-lite` 不在列表中，默认更新为 `sensenova-6.8-flash-lite`。

## 模型更新

按管理员要求，仅展示新版 Flash Lite、之前使用的 DeepSeek V4 Flash 和已实测成功的 Kimi K3。后台通过 `/v1/models` 同步这三项的文本能力及零定价元数据，缓存 5 分钟并合并并发请求；网络故障时使用最近的列表，60 秒后再尝试。不自动增加其他模型，不逐个测试。定价元数据为零不代表无限额度，套餐权限、积分、频率限制仍以平台实际响应为准。

当前套餐拒绝 `deepseek-v4.1-flash` 这个内部 ID，官方文档的 V4.1 名称使用 `deepseek-flash`，前者不进入下拉列表。图像生成模型不进入文本聊天列表。

前端读取最新默认模型，自动替换浏览器保存的失效选择；自定义提供商的模型名保持原样。兼容客户端发送旧 6.7/Nova-5-Pro 名称时，后端迁移到当前可用默认值。

## 密钥与额度

- `SENSENOVA_API_KEY` 只放在服务器环境配置中，代码、构建产物及模型列表响应不包含密钥。
- 登录用户可留空个人 Key 使用站点服务；自填 Key 优先，不会被站点 Key 覆盖。
- 站点 Key 只向固定官方地址发送，拒绝自定义地址覆盖。
- 单人每分钟最多 10 次、同时 1 个对话；全站每分钟最多 60 次、同时 4 个对话。单次输入最多 40000 字符，输出最多 4096 token。
- 当前限流是进程内实现，针对现有单 worker 部署；多 worker 部署需共享限流存储。
- 私密文件 `backend/sensenova.env` 必须权限 0600 并 Git 忽略。提供商错误内容中的 Key 会脱敏。

## 交互

默认快速回答，发送 `reasoning_effort=none`；可选择深度思考。Kimi 使用 `max_completion_tokens` 并省略非默认温度。界面提供停止生成，切页时取消请求。SSE 兼容分段 UTF-8、换行边界与无空格 `data:`，错误后退出思考状态。

403 提示套餐未开通，429 提示额度或频率限制；不无限重试，不自动消耗另一个模型的积分。

## 发布与回归

`test_chat_adaptation.py` 使用模拟上游及临时登录状态；`preview_chat.py` 使用临时数据库，不接触真实账户和额度。前端执行 `npm test` 和 `npm run build`。

`tools/deploy_chat.py` 生成不含密钥的定向包，发布时备份 SQLite、前后端文件及运行配置，将旧服务器代码里的密钥迁移到私密环境文件后重启。失败恢复应用及配置，保留数据库备份。`tools/verify_chat.py` 检查公开模型列表、匿名访问限制及前端版本。
