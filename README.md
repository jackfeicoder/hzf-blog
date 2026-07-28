# 个人博客 · CodeBlog

React (Vite) + FastAPI + SQLite/MySQL 的全栈技术社区，UI 风格参考 CSDN。

## 功能

- 多用户注册 / 登录（JWT）
- 发文章、草稿、Markdown 编辑 + 实时预览
- Markdown 渲染 + 代码高亮（highlight.js）+ XSS 清洗（DOMPurify）
- 分类筛选、标签、关键词搜索
- 点赞 / 收藏 / 阅读量
- 评论 + 二级回复
- 关注作者、个人主页、收藏夹
- 热门文章榜 / 作者影响力榜
- 数据库默认 SQLite，一个环境变量切换 MySQL

## 目录结构

```
hzf-blog/
├── backend/               # FastAPI 后端
│   ├── main.py            # 入口，启动时自动建表 + 创建管理员 + 预置分类
│   ├── database.py        # 数据库连接（SQLite / MySQL）
│   ├── models.py          # User / Post / Comment / Like / Favorite / Follow ...
│   ├── schemas.py         # Pydantic 模型
│   ├── auth.py            # JWT / 密码哈希
│   └── routers/           # auth / posts / comments / users
└── frontend/              # React 前端 (Vite)
    └── src/
        ├── api.js         # 后端 API 封装
        ├── AuthContext.jsx
        ├── components/    # Layout / PostCard
        ├── pages/         # 首页、文章、编辑器、登录注册、主页、排行榜
        └── index.css      # CSDN 风格全局样式
```

## 启动后端（conda）

```bash
conda activate hzf-blog          # 已创建过可跳过 create
# 首次：conda create -n hzf-blog python=3.11 -y
#        conda activate hzf-blog
#        pip install -r requirements.txt

cd backend
uvicorn main:app --reload --port 8000
```

首次启动会自动创建 SQLite 数据库 `blog.db`、管理员账户和 8 个默认分类：

- 用户名 `root`，密码 `123456`（可用环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 覆盖，**部署前务必修改**）

API 文档：http://localhost:8000/docs

### 切换 MySQL

```bash
pip install pymysql
# 先在 MySQL 中创建数据库：CREATE DATABASE blog CHARACTER SET utf8mb4;
export DATABASE_URL="mysql+pymysql://用户名:密码@localhost:3306/blog?charset=utf8mb4"
uvicorn main:app --reload --port 8000
```

## 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 。开发环境下 Vite 已配置代理，`/api` 请求会转发到 8000 端口。

## 使用流程

1. 访问 `/login`，用 root / 123456 登录；或 `/register` 注册新账号
2. 点「写文章」，正文支持 Markdown，可切换预览，选择分类和标签
3. 取消勾选「发布」可存为草稿，只在自己主页可见
4. 文章页可点赞、收藏、评论、回复、关注作者
5. 首页左侧分类筛选，右侧热榜 / 作者榜；顶部「排行榜」看完整榜单

## 部署要点

- 设置强随机的 `SECRET_KEY` 环境变量（JWT 签名密钥）
- 修改 `CORS_ORIGINS` 为你的正式域名（逗号分隔）
- 前端 `npm run build` 后用 Nginx 托管 `dist/`，并把 `/api` 反向代理到后端
- 生产建议用 MySQL 并定期备份；SQLite 备份则直接复制 `blog.db`
