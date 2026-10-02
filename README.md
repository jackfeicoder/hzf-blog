<div align="center">

# CodeBlog · 写作、学习与音乐的个人空间

一个可自部署的全栈技术社区，把 Markdown 博客、学习打卡、AI 对话与 Web 音乐播放器放在同一个站点。

[![Stars](https://img.shields.io/github/stars/jackfeicoder/hzf-blog?style=flat-square)](https://github.com/jackfeicoder/hzf-blog/stargazers)
[![Forks](https://img.shields.io/github/forks/jackfeicoder/hzf-blog?style=flat-square)](https://github.com/jackfeicoder/hzf-blog/forks)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)](LICENSE)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)

[在线体验](https://blog.120115.xyz:8443/) · [GitHub](https://github.com/jackfeicoder/hzf-blog) · [Gitee](https://gitee.com/jackfei2545/hzf-blog) · [问题反馈](https://github.com/jackfeicoder/hzf-blog/issues) · [参与贡献](CONTRIBUTING.md)

</div>

## 功能一览

### 写作与技术社区

- **Markdown 写作**：实时预览、代码高亮与复制、文章目录、阅读进度；支持草稿、分类、标签及全文关键词搜索。
- **社区互动**：点赞、收藏、评论和二级回复、关注作者、个人主页、站内通知。
- **内容发现**：最新/热门文章、作者榜、分页筛选、访客统计。
- **多端界面**：响应式布局、移动导航、浅色/深色主题。

### 学习打卡

- 按账户独立保存学习数据，每日安排 **Java 八股 5 题、Hot100 2 题、项目学习 1 项**。
- 完成/取消、重点标记、学习笔记、月度历史、轮次进度；未完成任务顺延。
- 题库支持文章解析预览、选择导入、手动维护、排序和停用；历史任务保留当天快照。
- 一轮结束后可开始全部复习或重点复习，默认项目顺序 HelloAgent → paicli → RAG。

### AI 与休闲

- **AI 对话**：提供商/模型配置、OpenAI 兼容接口、SSE 流式输出；使用自己的 Key 或管理员配置的 SenseNova Key。
- **看视频**：公开外站链接导航与搜索，管理员维护名称、简介、链接和顺序；点击后打开外站。
- **听音乐**：歌曲/歌手搜索、我喜欢、自建歌单、最近播放、歌词跟随与点击跳转、播放队列、音量、音质设置及顺序/随机/单曲循环。
- **共享推荐**：将 jackfei 的「我喜欢」作为公开推荐歌单，其他用户可播放并收藏到自己的歌单。
- **持续播放**：首次打开音乐模块后，站内切换页面保持播放；音源不可用时按优先级尝试其他源。

### 管理与性能

- 集中后台管理文章、用户、分类、评论及学习记录；普通用户仅编辑自己的文章，删除文章须验证操作者本人的密码。
- 路由按需拆包；公共列表短期内存缓存、重复请求合并、旧内容先显示再刷新；私人数据不进入公共缓存。
- 列表查询避免加载全文，正文与评论并行读取；播放器进度与歌曲列表分离订阅。
- 后端采用隔离数据库回归测试，前端使用 Node 内置测试。

> AI、音乐和外站可用性取决于对应服务；本项目不承诺第三方免费额度或所有曲目的可播放性。音乐脚本不随源码分发，需自行导入并配置隔离运行环境。

## 界面预览

![音乐推荐歌单与播放设置](docs/music-preview.png)

## 技术栈与环境

| 层级 | 技术与建议环境 |
| --- | --- |
| 前端 | React 18、React Router 6、Vite 5；建议 Node.js 22 + npm |
| 内容渲染 | marked、highlight.js、DOMPurify |
| 后端 | Python 3.11+、FastAPI、Uvicorn、Pydantic 2 |
| 数据与认证 | SQLAlchemy 2、SQLite、JWT、bcrypt；可配置 MySQL/PyMySQL |
| 部署 | Linux + Nginx + systemd，或 Docker Engine + Docker Compose v2 |
| 音源执行 | Linux 宿主机的独立 Docker 沙箱 + Node.js 20+、受限 HTTP 桥 |

默认 SQLite 适合个人站点和轻量部署。当前数据库自动化测试以 SQLite 为基准，更换数据库前请在测试环境验证。

## 本地开发

### 1. 获取源码

```bash
git clone https://github.com/jackfeicoder/hzf-blog.git
cd hzf-blog
# 国内镜像：https://gitee.com/jackfei2545/hzf-blog.git
```

### 2. 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell：.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
# Windows PowerShell：Copy-Item .env.example .env
```

编辑 backend/.env，设置强随机 SECRET_KEY 和 ADMIN_PASSWORD，保留 ADMIN_USERNAME=jackfei；随后启动：

```bash
uvicorn main:app --env-file .env --reload --host 127.0.0.1 --port 8000
```

首次启动自动建表、预置分类和创建管理员。ADMIN_* 仅用于空数据库初始化，修改环境变量不会重置已有账户。当前超级管理员与推荐歌单拥有者固定为用户名 **jackfei**，自部署时请先创建并保管好该账户。

- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 健康检查：[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- .env 并非自动读取：使用上述 --env-file，或由进程管理器注入环境变量。

### 3. 前端

另开终端，在仓库根目录执行：

```bash
cd frontend
npm ci
npm run dev
```

访问 [http://localhost:5173](http://localhost:5173)。Vite 将 /api 和 /uploads 代理到后端 8000 端口。生产环境也需同源反向代理。

## Docker Compose 部署

提供前端多阶段构建、非 root 后端容器、健康检查，以及数据库/上传文件的持久化卷。

> **范围说明**：基础 Compose 支持博客、打卡、视频导航、AI 配置及音乐搜索/歌词/歌单；第三方音乐脚本执行默认关闭。完整音源播放使用下方 Linux 宿主机方案。不要为了启用音源，直接把 Docker socket 挂进 Web 容器。

```bash
cp .env.example .env
# Windows PowerShell：Copy-Item .env.example .env
# 编辑 .env，替换 SECRET_KEY、ADMIN_PASSWORD，设置正式 CORS_ORIGINS
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs -f backend
```

默认访问 [http://localhost:8080](http://localhost:8080)。端口只绑定宿主机 127.0.0.1；对外服务请配置 HTTPS 反向代理，转发至 127.0.0.1:8080。可通过 APP_PORT 调整端口。

- 后端不直接暴露公网端口，前端 Nginx 同时转发 API 和上传文件。
- SQLite 位于后端 /data/blog.db，使用 blog-data 卷；上传文件使用 blog-uploads 卷。
- docker compose down 保留数据；**down -v 会移除数据卷**，请勿用于日常更新。
- 更新源码后执行 docker compose up -d --build；升级前备份数据库与上传文件。

根目录 .env 用于 Compose；backend/.env 用于源码开发，两者用途不同。

## Linux 源码部署

适合已有 Nginx、需要完整音源隔离执行或自行管理服务的环境。

1. 克隆代码、创建虚拟环境，安装 backend/requirements.txt。
2. 配置 backend/.env 的密钥、初始管理员和正式域名。
3. 在 frontend 执行 npm ci、npm run build。
4. 用 systemd 启动后端，Nginx 托管 frontend/dist 并转发 /api/、/uploads/。
5. 配置 TLS、防火墙与备份后，再开放正式域名。

示例 systemd 单元，按实际目录、虚拟环境和账户调整：

```ini
[Unit]
Description=CodeBlog API
After=network.target

[Service]
User=codeblog
WorkingDirectory=/srv/codeblog/backend
EnvironmentFile=/srv/codeblog/backend/.env
ExecStart=/srv/codeblog/backend/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

确保 codeblog 用户有权写入 SQLite 所在目录与 backend/uploads；.env 仅服务账户可读。Nginx 关键配置如下，TLS 证书及完整 server 配置由部署者提供：

```nginx
root /srv/codeblog/frontend/dist;
client_max_body_size 6m;

location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 620s;
}
location /uploads/ { proxy_pass http://127.0.0.1:8000; }
location /assets/ {
    try_files $uri =404;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
location = /index.html { add_header Cache-Control "no-cache"; }
location / { try_files $uri $uri/ /index.html; }
```

关闭代理缓冲使 SSE/音频及时输出；SPA 回退确保 /music、/study 等页面直接访问正常。使用 CDN 时不要对 /api/* 设置「缓存所有内容」，私人接口与播放凭据必须绕过公共缓存。

### 完整音乐音源

Linux 宿主机安装 Docker Engine 和 Node.js 后，先构建独立运行镜像。在后端虚拟环境中执行：

```bash
cd backend
python -c "import sys; sys.path.insert(0, '../tools'); from prepare_music import build; build()"
# 在服务环境中设置 MUSIC_SANDBOX=docker，并重启后端
```

以 jackfei 登录「听音乐 → 音源管理」，自行导入脚本、测试并启用。脚本使用一次一个、只读、无网络、非 root、资源受限的临时容器，上游请求由受限 HTTP 桥处理。

**权限提示**：宿主机适配器需要调用 Docker CLI；访问 Docker daemon 的服务账户拥有很高的主机权限。建议使用独立主机/隔离虚拟机，审查服务权限；Node vm 不代替操作系统隔离。兼容性与限制见 [音乐文档](docs/music.md)。

### 可选 MySQL

安装 pymysql，先创建数据库及拥有对应库权限的专用用户：

```bash
pip install pymysql
# CREATE DATABASE blog CHARACTER SET utf8mb4;
```

设置 DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/blog?charset=utf8mb4，对密码中特殊字符进行 URL 编码。先备份并迁移数据；修改地址不会自动把 SQLite 数据搬到 MySQL。

## 配置参考

| 变量 | 用途 |
| --- | --- |
| SECRET_KEY | JWT 签名密钥；生产环境必须替换默认值 |
| ADMIN_USERNAME / ADMIN_PASSWORD | 空数据库初始化，建议用户名 jackfei |
| CORS_ORIGINS | 完整来源，逗号分隔，含协议及非默认端口 |
| DATABASE_URL | 源码运行默认 sqlite:///./blog.db |
| SENSENOVA_API_KEY | 可选站点共享 Key；留空时使用者自备 |
| MUSIC_SANDBOX | 宿主机完成隔离配置后设为 docker，否则脚本执行关闭 |
| APP_PORT | Compose 本地访问端口，默认 8080 |

不要提交 .env、真实密钥、数据库、上传文件或第三方音源归档。AI 页会在浏览器本地保存用户输入的 Key，公共电脑使用后请清除；Key 会传给服务端代理与所选模型提供商。

## 数据、缓存与备份

- **业务数据**保存在配置的数据库；上传图片存磁盘/持久化卷。
- **公共列表缓存**在浏览器内存中，30 秒内复用，最多保留 5 分钟旧数据显示；账户变化及相关写操作使缓存失效。
- **音乐元数据缓存**在后端内存中，搜索/歌词/解析地址有有限有效期，重启后清空，不永久保存音频文件。
- **私人歌单、打卡与后台数据**不进入公共缓存；推荐仅公开指定账号的「我喜欢」。

SQLite 备份建议使用在线备份 API 或 .backup，而不是在写入期间直接复制文件；同时备份上传目录和代码/构建版本。当前通过 create_all 创建新表，并非完整数据库迁移系统。

默认单个 Uvicorn worker。内存限流、缓存、音源信号量和播放票据尚非多进程共享，扩容前应设计共享状态与数据库迁移。

## 目录结构

```text
hzf-blog/
├── backend/
│   ├── main.py                 # 应用、建表、初始化与路由注册
│   ├── auth.py                 # JWT、密码、管理员与删除验证
│   ├── database.py             # SQLAlchemy 连接与会话
│   ├── models.py / schemas.py  # 博客模型与输入输出
│   ├── study_models.py         # 题库、轮次、进度与快照
│   ├── media_models.py         # 视频导航
│   ├── music_models.py         # 音源、歌单、歌曲
│   ├── music_worker.py         # Docker 音源执行器
│   ├── music_http.py           # 受限上游 HTTP 桥
│   ├── music_runtime.cjs       # LX API 兼容运行时
│   ├── routers/               # 博客、AI、打卡、视频、音乐、后台
│   ├── tests/                 # 隔离数据库回归与本地预览
│   └── Dockerfile
├── frontend/
│   ├── src/pages/             # 路由页面
│   ├── src/components/        # 导航、文章卡片、密码确认
│   ├── src/music/             # 持久播放器、状态、队列、音源 UI
│   ├── src/api.js             # 博客 API 与缓存失效
│   ├── src/queryCache.js      # 有界内存缓存与请求合并
│   ├── tests/                 # API、缓存、播放控制测试
│   ├── nginx.conf             # Compose 同源静态站点/反向代理
│   └── Dockerfile
├── docs/                      # 模块、权限、性能说明
├── tools/                     # 现有站点的定向备份/发布工具
├── compose.yaml               # 基础容器部署
├── .env.example               # Compose 环境模板
├── CONTRIBUTING.md
├── NOTICE
└── LICENSE
```

tools/deploy_*.py 面向维护者现有服务器，包含固定服务名与路径，不是通用安装脚本；请先审查和适配。

## 测试与模块文档

```bash
cd backend
python -m unittest discover -s tests -p 'test_*.py' -v
cd ../frontend
npm test
npm run build
```

后端覆盖用户隔离、关联清理、打卡并发、音源边界与公开推荐；前端覆盖缓存失效、请求竞态、队列、歌词解析及模式切换。

详细说明：[学习打卡](docs/study-checkin.md) · [管理权限](docs/admin-permissions.md) · [视频导航](docs/media.md) · [音乐播放器](docs/music.md) · [性能优化](docs/performance.md)

## 参与贡献

欢迎反馈问题、完善文档和测试、提交功能改进。请阅读 [贡献指南](CONTRIBUTING.md)，让每个 PR 聚焦可验证的改动。

维护者：[jackfeicoder](https://github.com/jackfeicoder)

[![贡献者](https://contrib.rocks/image?repo=jackfeicoder/hzf-blog)](https://github.com/jackfeicoder/hzf-blog/graphs/contributors)

完整记录见 [Contributors](https://github.com/jackfeicoder/hzf-blog/graphs/contributors) 和 [提交历史](https://github.com/jackfeicoder/hzf-blog/commits/main/)。头像与统计由第三方服务动态生成，可能存在刷新延迟。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=jackfeicoder/hzf-blog&type=Date)](https://star-history.com/#jackfeicoder/hzf-blog&Date)

数据由 Star History 提供；星标很少或上游限流时，可点击查看完整页面。

## 开源协议与致谢

项目源码采用 [Apache License 2.0](LICENSE)，署名见 [NOTICE](NOTICE)。第三方依赖、导入的音源脚本、音频、歌词、封面和外站内容各自遵循原作者/服务方的许可，不因本项目许可而获得额外授权。

感谢 React、FastAPI、Vite、SQLAlchemy、marked、highlight.js、DOMPurify 等项目。音乐体验与兼容能力参考 [LX Music](https://github.com/lyswhut/lx-music-desktop)；README 组织参考 [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template) 的功能、开发与部署结构。
