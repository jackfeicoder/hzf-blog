# 参与贡献

欢迎通过 [Issues](https://github.com/jackfeicoder/hzf-blog/issues) 报告问题、提出建议，通过 Pull Request 提交改进。

## 开发流程

1. Fork 仓库，从 `main` 创建功能分支。
2. 按 [README](README.md) 配置本地环境，使用测试账号和临时数据库。
3. 每次提交聚焦一项改动，同时补充测试与必要的文档。
4. 提交前运行后端测试、前端测试和生产构建；PR 描述写明背景、验证方式与界面截图。
5. 等待维护者审查。不要将生产数据库、用户数据、上传文件或 API Key 放进 PR。

```bash
cd backend
python -m unittest discover -s tests -p 'test_*.py' -v
cd ../frontend
npm ci
npm test
npm run build
```

建议提交消息使用 `feat`、`fix`、`perf`、`test`、`docs`、`chore` 等前缀；保持改动可审查，并说明涉及的模块。

## 提交署名

使用与你的 GitHub 账户关联且验证过的邮箱，或 GitHub 提供的 noreply 邮箱：

```bash
git config user.name "YOUR_GITHUB_USERNAME"
git config user.email "YOUR_VERIFIED_EMAIL"
```

## 约定

- 数据权限在后端校验，前端隐藏按钮不代替权限控制。
- 私有接口、账号切换和缓存失效行为需要测试覆盖。
- 新音源须通过隔离执行与样本验证，不提交第三方凭据或归档脚本。
- 按 Apache-2.0 许可提交贡献，并保留第三方项目的许可和署名。
