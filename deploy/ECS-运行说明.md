# ECS 部署与维护

2026-10-08 部署地址：https://120.27.205.41 。项目目录 `/opt/knowledge-base`，SSH 别名 `aliyun_41`。

## 已部署内容

- 前端本机执行 `npm run build`，上传 `frontend/dist`，由 Caddy 提供服务。
- FastAPI 容器仅在 Docker 内网监听 8001；Caddy 对外提供 80/443 并代理 `/api`。
- 使用 MySQL；启动连接失败时使用 `/data/knowledge_base.db` SQLite 备用快照。运行中不会自动切换，备用快照不与 MySQL 实时同步。
- IP 的 Let's Encrypt 短期证书由 Caddy 自动续期；保持 80/443 可达并保留 `data/caddy`。
- 原 nginx 8080 网站保留，部署前后页面 SHA256 一致；宝塔 8888 仍在监听。
- 容器自动重启，Docker 开机启动，后台任务使用单个后端进程。

## 数据迁移结果

本地 SQLite 与现有 MySQL 合并：4 个知识库、12 条资料记录、1,923 条人才记录、28 个会话、7,120 个分片和 3,678 条向量。人才记录数不代表去重人数。

保留 MySQL 的现有账号密码和默认模型；本地登录会话未迁移。资料原件及模型密钥文件已复制。迁移前 MySQL 备份和本地 SQLite 快照在本机 `backend/storage/backups/`。

历史向量保留原模型标记，没有批量重新请求向量模型。与当前模型不兼容时按应用既有逻辑回退检索；重建向量会消耗模型额度。原有一个失败导入任务保留，未自动重试。

## 日常操作（每条命令前为说明）

```sh
# 登录服务器。
ssh aliyun_41

# 切换到项目根目录，后续 compose 命令依赖此目录。
cd /opt/knowledge-base

# 查看前后端状态，backend 应为 healthy。
docker compose -p knowledge-base -f deploy/compose.ecs.yaml ps

# 查看最近的服务日志。
docker compose -p knowledge-base -f deploy/compose.ecs.yaml logs --tail=100 backend web

# 检查当前后端是否就绪。
curl --fail https://120.27.205.41/ready

# 配置文件更新后重新创建容器，使 production.env 生效。
docker compose -p knowledge-base -f deploy/compose.ecs.yaml up -d

# 后端代码更新后构建并启动；不会清除挂载的数据。
docker compose -p knowledge-base -f deploy/compose.ecs.yaml up -d --build backend

# 检查每日备份的下一次执行时间。
systemctl list-timers knowledge-backup.timer

# 立即进行一次数据和原件备份。
systemctl start knowledge-backup.service

# 确认备份成功，无需依赖无输出的 start 命令判断。
journalctl -u knowledge-backup.service -n 10 --no-pager
```

## 配置与备份

`deploy/production.env` 保存运行参数和密钥，不提交 Git。上传原件在 `data/storage/uploads`，加密主密钥在 `data/storage/security`，两者与数据库共同保管。不要删除主密钥，否则数据库内的模型 API Key 将无法解密。

每日北京时间 03:30 后随机延迟最多 5 分钟备份到 `data/backups/mysql-时间戳/`：SQLite 一致性快照、原件压缩包和 SHA256 校验清单。备份任务不会覆盖运行中的 SQLite 备用库；备份也不包含登录会话和加密主密钥。主密钥需另行安全保管。历史备份不自动删除，定期检查磁盘并在确认异地副本后清理。

恢复时先停止后端写入并备份当前状态，将选定且通过完整性检查的 SQLite 快照放到 `data/knowledge_base.db`、恢复匹配的原件和主密钥，确认 UID 10001 可读写，再将 `APP_DATABASE_MODE=sqlite` 重建后端容器。不要把 SQLite 文件直接当作 MySQL 导入文件；切回 MySQL 前必须处理恢复期间新增数据，避免双库分叉。

首次部署时，本机后端已停止以避免两个后台任务进程同时处理同一 MySQL 队列。本机继续开发应使用独立 SQLite 或关闭本机后台任务。

## 本次验收

前端构建通过；后端测试运行 91 项，90 项通过、1 项按条件跳过。公网 HTTPS 证书校验通过，首页、健康检查、登录、MySQL 状态、知识库列表、全部 5 个已关联原件的下载及预览、人才列表、会话列表通过。默认聊天模型 `qwen3.8-max` 实际回复“连接成功”，`qwen3.7-text-embedding-flash` 实际返回 1024 维向量。

首次完整备份已下载至本机 `backend/storage/backups/deployment-verified-20261008.tar.gz`，与服务器 SHA256 一致，并解压数据库进行完整性和外键校验。每日后续备份目前只保存在服务器，未配置自动异地同步。

浏览器自动化环境当前不可用，本次页面验收使用真实 HTTPS 请求及 API 链路测试，未执行浏览器交互测试。
