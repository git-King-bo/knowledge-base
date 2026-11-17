# companyOps Docker 部署

入口：http://future.ops.originhub.tech 。服务器 `companyOps`（139.196.251.24），目录 `/opt/knowledge-base`。

线上使用独立 SQLite：`/opt/knowledge-base/data/knowledge_base.db`，不直接连接本地 MySQL。
2026-11-16 已从本地实际 MySQL `wangbo_pro` 的一致性快照迁移：4 个知识库、12 份原件、1,923 条人才记录、60 个会话、7,535 个分片、7,525 条向量和 5 个模型服务配置；相应加密密钥仅保存在服务器数据目录。
这是一次性迁移，不是 MySQL/SQLite 自动双向同步，之后两边新增数据彼此独立。
迁移前线上空库与配置备份位于 `/opt/knowledge-base/backups/pre-data-sync-20261116T060654Z/`。
宿主机 Nginx 继续提供原 `future_ops.originhub.tech` 服务；新域名单独代理到
`127.0.0.1:18080`，由 Docker 内的 Caddy 提供前端并代理 FastAPI。

## 自动部署

本机需要 Docker、SSH，以及 tar、openssl 等系统工具。启动 Docker Desktop 后，在项目根目录运行：

```sh
bash deploy/deploy.sh
```

不加参数发布前后端，也可按需指定：

```sh
bash deploy/deploy.sh frontend  # 只构建和更新前端
bash deploy/deploy.sh backend   # 只构建和更新后端
```

版本号自动生成。脚本执行镜像构建、打包、SSH 上传、校验、更新容器及健康检查，无需云镜像仓库。
首次部署必须发布前后端；单独发布保留另一端的镜像版本。发布后端或全部服务前备份数据；仅发布前端不停止后端、不打包正在写入的数据库。
终端只显示三步进度和结果，详细输出保存在项目 `logs/deploy-版本号.log`；失败会立即停止并提示日志位置。

如果本机已有 amd64 的 `knowledge-base-release-test:backend/frontend` 镜像、后端依赖完全一致且 pnpm 可用，自动复用运行环境并重新构建当前代码和前端。
否则按 Dockerfile 完整构建，需要网络可访问镜像仓库和依赖源。
Shell 脚本 `deploy.sh` 负责本机构建和上传，`company-apply.sh` 负责服务器备份和容器更新。
这是按命令触发的自动部署，GitHub Actions 只保留基础测试 CI。

## 账号与模型

账号是 `admin`，初始随机密码只保存在服务器：

```sh
ssh companyOps 'cat /opt/knowledge-base/data/security/initial-admin-password.txt'
```

账号密码以实际数据库为准，初始密码文件不会随重置自动更新。
迁移已保留原模型服务、密钥及默认服务选择。迁移时原默认模型曾因 HTTP 限制不能调用；后续已按指定地址配置精确 HTTP 例外并切换集中模型配置，详见下方“集中更换模型”。迁移验收未调用付费模型。
配置真实模型前，在服务器 `/opt/knowledge-base/deploy/company.env` 设置
`APP_PROVIDER_ALLOWED_HOSTS` 为模型接口的准确域名（多个以逗号分隔），重建容器后在页面添加模型地址、模型名及密钥。
默认不允许内网模型地址。不要把 env、数据目录、密钥和密码提交到 Git。

## 运维

登录 `ssh companyOps` 后执行：

```sh
cd /opt/knowledge-base
docker compose -p knowledge-company --env-file deploy/company-version.env -f deploy/compose.company.yaml ps
docker compose -p knowledge-company --env-file deploy/company-version.env -f deploy/compose.company.yaml logs --tail 100
curl --fail http://future.ops.originhub.tech/ready
```

更新 company.env 后，用同一 compose 命令的 `up -d` 重建容器。镜像不自动清理。
数据库、原件、加密密钥都在 `data/`，目录归容器用户 10001 所有。
容器配置了自动重启，Docker 已启用开机启动；日志按 10 MB × 3 轮转。

后端或全量发布在停止后端写入后将完整 data 打包到 `backups/UTC时间/data.tgz`，包含密钥，应按敏感数据保管。
发布失败会尝试恢复上一版 compose、镜像和 Nginx 配置；数据库不自动降级。
若新版本改变数据库结构，旧镜像可能不能直接运行，应在维护窗口用匹配的备份恢复，并考虑恢复后新增数据。
目前没有自动异地备份，也没有自动执行旧版 MySQL 发布控制器。

## HTTP 与 HTTPS

当前按要求使用 HTTP，Nginx 对 `kb_session` 移除 Secure 属性以保证登录可用，保留 HttpOnly 和 SameSite。
配置文件 `/etc/nginx/sites-available/knowledge-base`。
以后启用 HTTPS 时，申请匹配 `future.ops.originhub.tech` 的证书，将 CORS 地址改为 HTTPS，
删除 `proxy_cookie_flags kb_session nosecure`，并更新 Nginx 为 HTTPS 入口。
已有 `*.originhub.tech` 证书不覆盖此域名。

## 页面更新提醒

前端发布会生成 `/version.json`，已打开的新页面每分钟检查，并在回到标签页时补查。
发现更新仅提示，提交/上传/生成回答期间禁止刷新；问答输入可由用户选择保存临时草稿。
首次启用时，旧页面需手动刷新一次才能加载检测代码。
前端/全量发版保留历史哈希资源在 `data/frontend-assets`，不会自动清理，应监控磁盘。
设计、状态规则及测试细节见 [版本更新实现细则](../docs/版本更新实现细则.md)。

### 2026-11-16 数据同步验收

数据库完整性、外键、12 份原件存在性及模型密钥解密均通过。
通过 HTTP 接口验证管理员登录、知识库列表、会话列表、人才总数和全部 5 个已关联原件的下载及预览。
原始 MySQL 未修改，源库登录会话不复制，未重新生成向量。

更新提示只对加载了检测代码的旧页面生效；发版后刷新或重新打开页面已直接加载最新版，不再显示“有新版本”。

## 集中更换模型（2026-11-16）

密钥仅保存在运行环境，不提交代码，不打包进镜像：

- 线上：`/opt/knowledge-base/deploy/models.env`，权限 0600，由 Compose 加载；聊天走内网 `192.168.0.186:8000`。
- 本地：`backend/models.env`，权限 0600，在 backend 目录启动时自动加载；聊天走公网 `47.116.168.243:8000`。
- 无密钥模板：`deploy/models.env.example`。

采用项目原生配置名，对应用户提供的名称如下：

| 原名称 | models.env 中的名称 |
| --- | --- |
| MODEL_NAME | AGENT_DEFAULT_MODEL |
| LLM_API_URL | AGENT_DEFAULT_API_URL |
| LLM_API_KEY | AGENT_DEFAULT_API_KEY |
| EMBEDDING_MODEL_NAME | AGENT_EMBEDDING_MODEL |
| EMBEDDING_API_URL | AGENT_EMBEDDING_API_URL |
| EMBEDDING_API_KEY | AGENT_EMBEDDING_API_KEY |
| TALENT_AGENT_EMBEDDING_DIMENSION | AGENT_EMBEDDING_DIMENSION |

聊天为 `qwen3.8`，向量为 `bge-m3` / 1024 维。完整 `/chat/completions`、`/embeddings` 路径会在加载时规范化到 base URL，避免重复拼接路径。

`APP_SYNC_ENV_PROVIDER=true` 表示文件管理默认模型：启动时把配置写入 `provider-agent-default`，密钥加密入库，并同步模型列表。页面对这个服务的修改会在下一次启动时被文件配置覆盖；其他服务记录保留。
规划模型由文件中的 `APP_TALENT_PLANNER_PROVIDER_ID`、`APP_TALENT_PLANNER_MODEL` 指定。

HTTP / 内网访问仅对 `APP_PROVIDER_HTTP_ORIGINS` 中明确指定的 scheme、host、port 放行，且仍需满足 `APP_PROVIDER_ALLOWED_HOSTS`。没有全局开放任意 HTTP 或内网地址。更换主机或端口时也需更新这两项。

修改线上 models.env 后，在服务器运行（无需重新构建镜像）：

```sh
cd /opt/knowledge-base
docker compose -p knowledge-company --env-file deploy/company-version.env -f deploy/compose.company.yaml up -d --no-deps --wait backend
```

必须让 Compose 重建容器读取新环境，单纯 docker restart 不会重新读取 env 文件。本地修改后重启后端。

向量模型切换后，旧模型向量不会被当作新模型使用；已有知识、原件和旧向量保留。需要 bge-m3 全量向量检索时再显式重建索引；本次没有自动重建，避免未确认的全量模型调用。

本次集中配置验收：后端201项测试（1项跳过）通过，聊天与向量适配器实测通过；原503查询返回HTTP 200及SSE meta/delta/done，最终执行轨迹为success。模型切换本身未自动重建；之后已按明确指令建立bge-m3人才级索引。


## 人才级 bge-m3 索引（2026-11-16）

已为人才检索、人才库-900、新知识库建立完整人才级索引，覆盖分别为906、906、111条来源记录，维度1024。
索引位于服务器 `data/search-index`，旧模型向量和原件保留。后续仅在资料或模型发生变化时重建相应版本。
实测简单查询、混合主题、排序与分页在1秒内；复杂冷查询及追加条件追问约10.6秒，尚未满足5秒目标。
详见 [索引与性能评估](../docs/人才搜索索引与性能评估-20261116.md)。
