# companyOps Docker 部署

入口：http://future.ops.originhub.tech 。服务器 `companyOps`（139.196.251.24），目录 `/opt/knowledge-base`。

这是独立的新 SQLite 数据库，不连接旧服务器/MySQL，不导入本机资料或模型密钥。
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

初次登录后在页面修改密码。初始库不包含真实模型服务密钥；应用自带 Mock 服务仅用于联通测试。
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
