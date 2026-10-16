# 欢迎页与作者简介

## 访问规则

- `/welcome`：未登录、未保存登录会话且第一次访问无查询参数/锚点的首页时展示。
- “进入博客”前往 `/register`；已有账号入口前往 `/login`。
- 点击以上入口或成功识别登录用户后，在当前浏览器保存 `blog_welcome_seen_v1=1`。之后访问首页不重复展示。
- 已登录用户、文章/音乐/打卡等直达链接不受拦截；分享链接不要求先注册。
- `/about`：所有用户可主动访问。入口位于网站页脚和侧栏菜单。
- 清除站点存储、更换浏览器或新无痕会话会重置首次访问记录。浏览器禁用存储时使用当前页面内存兜底。

## 内容与隐私

作者卡片从 `/api/users/administrator` 异步读取简介与头像；网络慢时先展示页面和默认简介，不等待图片。GitHub、Gitee、CSDN 使用独立外链按钮。

管理员账号展示字段仍使用 `administrator` / `管理员`。简介正文、URL 和其他用户输入不做账号字符串替换。个人主页中的 HTTP(S) 链接可点击，拒绝带凭证的链接；文本使用 React 转义，不渲染任意 HTML。

这是展示逻辑修复，不更改数据库中的简介或用户数据。

## 验证与发布

前端 `npm test` / `npm run build`，后端使用项目虚拟环境执行 `python -m unittest discover -s tests -p 'test_*.py' -v`。

`backend/tests/preview_welcome.py` 使用临时 SQLite 数据库提供桌面、手机及登录状态验收，不接触线上账户。

`python tools/deploy_welcome.py pack` 生成定向发布包。Linux staging 必须是 `/tmp/hzf-study-welcome-*`；发布前备份 SQLite、相关代码及前端产物。复用发布工具先测试、重启并健康检查，再切换前端入口；失败恢复应用文件并保留数据库备份。发布后运行 `verify_welcome.py` 做公开页面、资源、简介原文的只读检查。
