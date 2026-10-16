# 本地灾难恢复副本

代码仓库不包含线上用户数据。服务器到期前，需要单独保存数据库、上传资源、运行数据、R2 对象与部署配置。

## 导出与校验

`tools/export_server_recovery.py` 在现有 Linux 博客服务器运行：

- SQLite 使用在线 backup API，包含已提交的 WAL 数据；不停止服务、不覆盖线上文件。
- 导出实际代码、前端构建、上传资源、完整歌曲缓存、歌词及地址/路由索引。
- 下载该博客配置的 R2 桶对象，保留原 key、Content-Type 和 Cache-Control。
- 保存该博客的 systemd、Nginx、env 文件及引用的证书/私钥。
- 排除历史发布备份、旧前端备份、可重建的虚拟环境/node_modules、Git 和临时下载。
- 输出压缩包路径、SHA256、数量和体积，不输出密钥、歌词、用户信息或签名 URL。

先在本地创建 Git 仓库之外的私密目录，限制目录访问权限，再下载导出的压缩包。
将导出器输出的 SHA256 作为可信值运行：

```text
python tools/verify_recovery_export.py ARCHIVE.tar.gz NEW_SNAPSHOT_DIRECTORY SHA256
```

该命令拒绝越界路径及链接，逐文件校验大小和 SHA256，并对全部 SQLite 执行 quick_check。
解压目标必须是新目录，不会覆盖正在开发的项目。

另存当前 Git 全历史及依赖版本，例如：

```text
git bundle create /PRIVATE/DIRECTORY/code-history.bundle --all
git bundle verify /PRIVATE/DIRECTORY/code-history.bundle
```

Linux 依赖可按 requirements/package-lock 与记录的包版本重建，无需把已安装依赖复制到 Windows。

## 恢复注意事项

恢复副本包含真实用户数据、密码哈希、站点密钥、音源脚本与 TLS 私钥，不能作为公共仓库内容发布。
主数据库、uploads、.runtime、.music-cache 应保留相对路径；参考归档中的服务配置调整新主机的绝对路径、文件所有者和私密权限。
R2 独立于阿里云，原桶正常时可以继续使用；重建时按原对象 key 和 metadata 上传，保持图片链接有效。
先验证站点功能、内部音频入口和管理员权限，再将域名 DNS 指向新主机。

这是手动时间点快照，而不是持续同步；后续新数据需要重新导出。建议在另一块硬盘或可信设备上再保留一份副本。
