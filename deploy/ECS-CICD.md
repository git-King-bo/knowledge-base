# 镜像部署、灰度发布与指定版本回滚

## 当前接入状态（2026-10-09）

代码已加入 GitHub Actions 构建/发布工作流和服务器发布控制器。前后端 amd64 镜像已在本机构建，并在隔离 MySQL 与 Docker 环境完成灰度、全量切换、指定版本回滚、撤销灰度、数据库版本不兼容拒绝的演练。

**生产站点仍运行原版本，尚未执行首次 bootstrap。** 首次接管需要先把本次代码推送到 GitHub、配置下述两个 Secrets，并成功构建一版镜像。目前本机 `git ls-remote origin HEAD` 返回 GitHub SSH 权限错误；不要把工作流文件已存在当作流水线已运行。

## 发布流程

```text
GitHub main / v* 标签 / 手动构建
  → 后端与前端测试、发布安全测试
  → 构建 linux/amd64 前后端镜像
  → GHCR 保存镜像，产出 release.json（镜像 digest）
  → 人工触发 stage：新旧版本并行，仅测试浏览器进入新版
  → 验收通过后 promote：切换正式入口和单例后台任务
  → 有问题 rollback：重新启动指定历史版本并切换入口
```

服务器只需要镜像、发布工具、运行配置和持久化数据。不会在 ECS 上运行 npm/pip 安装或构建业务代码。已有源码暂时保留作为应急材料，不影响镜像运行，首次接管验收后再另行清理。

外层 Caddy 继续负责 80/443 和证书，每个版本有前端/API 容器。正式流量与灰度流量共用 MySQL、上传原件和加密密钥；只有正式版本的一个后台任务容器运行。原 nginx 8080 网站不变。发布串行执行，禁止同时启动多轮灰度。

## 一次性：配置 GitHub

1. 修复本机 GitHub SSH 登录，把本次部署相关变更提交、推送到 `git-King-bo/knowledge-base`。首次提交需要包含前一轮新增的 `backend/scripts/snapshot_mysql.py`、`deploy/backup-ecs.sh` 等依赖文件，不要只提交两个 YAML。
2. 在仓库 **Settings → Environments** 创建 `production`，限制仅受信任的 `main` 分支发起部署；按团队需要配置审批人。手动运行 Deploy release 时选择 `main`。
3. 在 `production` 的 **Environment secrets** 添加下面两项。密钥只粘贴到 GitHub Secret 输入框，不发送到聊天、不提交 Git。

| Secret | 内容来源 |
|---|---|
| `DEPLOY_SSH_KEY` | 本机 `deploy/.credentials/id_ed25519` 文件的完整内容 |
| `DEPLOY_KNOWN_HOSTS` | 本机 `deploy/.credentials/known_hosts` 文件的完整内容 |

专用密钥已限制为 `kb-release` 发布动作，禁止交互式 Shell、任意命令与 SSH 转发；它不是日常 root 登录密钥。`deploy/.credentials/` 同时被 Git 和 Docker 构建上下文忽略。服务器强制入口是 `deploy/ssh-release.py`，不要给它普通 Shell 授权。

4. 查看仓库 Actions 设置，允许当前工作流运行。Build 工作流只请求 `contents: read` 和 `packages: write`；Deploy 只请求读取镜像和构建产物。GHCR 包应保持 **Private**，并允许本仓库的 Actions 访问。发布使用任务临时 `GITHUB_TOKEN` 拉取镜像，服务器不长期保存 GHCR Token。
5. 首次 Build 完成后，在运行 Summary 记录版本号与 Run ID。版本格式类似 `sha-0123456789ab-r123456789-a1`，含源码提交及构建次数；实际发布固定 digest，不使用 `latest`。同一版本号不允许改成另一组镜像。

参考：[GitHub 镜像发布](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)、[环境保护规则](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments)。

## 第一次接管当前网站

在 GitHub **Actions → Deploy release → Run workflow** 中选择：

- Branch：`main`
- action：`bootstrap`（仅第一次使用）
- version：复制 Build Summary 的完整版本号
- build_run_id：复制对应构建 Run ID

工具会拉取已构建镜像，检查数据库版本、启动新接口和前端、备份数据，再接管现有 Caddy 路由和后台任务。原后端容器停止但不删除；接管前 Caddy 配置保存在 `releases/legacy-Caddyfile`。确认首页、登录、资料预览、聊天、导入均正常后，这一版就成为后续回滚的初始版本。

bootstrap 不允许在已接管后再次运行，后续发布都使用 stage/promote。

## 日常发布与灰度验收

1. 推送 main 或版本标签，等待 **Build release images** 成功，记录版本号和 Run ID。
2. 手动运行 **Deploy release**，action=`stage`，填写版本号和 Run ID。
3. 在部署日志找到 `Preview: https://120.27.205.41/__release/preview/<随机值>`，用测试浏览器打开，再正常登录。该链接只切换浏览器路由，不绕过账号权限。
4. 同一浏览器的页面和 `/api` 请求都进入候选版本；其他浏览器继续使用正式版。通过开发者工具响应头 `X-KB-Release` 确认实际版本。退出灰度访问 `https://120.27.205.41/__release/stable`，或清除该站点 Cookie。
5. 检查登录、知识库、资料预览、聊天和导入等本次改动涉及的功能。灰度期间导入队列仍由正式版本 worker 执行；涉及队列格式变更的代码必须向前兼容，不能只靠 API 灰度证明新 worker 已验证。
6. 验收通过后再次 Run workflow，action=`promote`，version 填当前候选版本，Run ID 留空。切换前自动备份；健康/路由验证失败自动恢复原正式版本。没有通过验收时 action=`abort`，撤销候选版本。

这是**指定浏览器灰度**，不是 10%/50% 随机流量灰度。单台 2 核 2 GB 的机器仅保持一个候选版本，不提供跨机器高可用。发布后旧 API/前端短暂保留以服务已有连接，可执行 retire 停止它们，镜像和版本记录仍保留。

## 回滚到指定版本

在 **Deploy release → Run workflow** 选择 action=`rollback`，version 填之前已登记的完整版本号，Run ID 留空。历史版本无需重新构建、无需重新下载 Actions artifact；服务器保存其镜像 digest 和当时的环境文件。

也可以通过日常管理员 SSH 执行：

```sh
# 登录服务器；这里使用日常管理员密钥，不是 CI 的受限密钥。
ssh aliyun_41

# 进入项目目录。
cd /opt/knowledge-base

# 查看 active、previous、candidate 以及全部已登记版本。
python3 deploy/release.py status

# 如正在灰度，先撤销候选版本，再进行历史版本回滚。
python3 deploy/release.py abort

# 将下面示例替换为 status 列出的真实版本号。
python3 deploy/release.py rollback sha-0123456789ab-r123456789-a1

# 确认流量实际进入目标版本；响应头包含 X-KB-Release。
curl --fail --include https://120.27.205.41/ready

# 查看当前各版本容器；后台任务角色为 worker。
docker ps --filter label=kb.release

# 停止/删除不再承载流量的历史容器；不删除镜像、配置或数据库。
python3 deploy/release.py retire
```

回滚的是**前端 + API + worker + 该版本环境配置**；不会还原 MySQL 或删除发布后新增的数据。依赖外部服务、API Key 或文件格式的变更也需要兼容旧版本；已失效的旧凭据不会因为镜像回滚而重新生效。当前登记版本的环境文件是不可变快照，配置修改也应随一个新版本发布。

## 数据库变更与回滚边界

版本发布强制 `APP_DATABASE_MODE=mysql`，不允许某个灰度实例自动改写 SQLite。SQLite 备份仍保留作为管理员应急恢复材料。运行 API/worker 时 `APP_MIGRATION_MODE=check` 只校验 Alembic 版本，不自动升级数据库。

目标镜像的 schema 与数据库不一致时，stage/rollback 会拒绝执行；不会自动运行 downgrade，也不会覆盖生产库恢复旧备份。涉及改表的发布需要另行制定维护计划、备份、验证 SQL，并为旧程序保留兼容窗口。当前工具对 schema 要求完全一致，因此跨 schema 版本不支持一键回滚，需先确认兼容或提供新修复版本。

## 中断恢复、备份和维护

```sh
# 如 SSH 中断或机器重启导致 pending.json 存在，先查看状态。
python3 deploy/release.py status

# 根据写前日志恢复上次切换前的 worker 与路由；然后再次查看状态。
python3 deploy/release.py recover

# 主动备份当前 MySQL 一致性快照与上传原件。
python3 deploy/release.py backup

# 检查每日备份任务；首次接管后它会自动改为备份当前版本。
systemctl list-timers knowledge-backup.timer
journalctl -u knowledge-backup.service -n 20 --no-pager
```

状态/版本清单/配置在 `releases/`，备份在 `data/backups/release-时间戳/`，证书仍由现有 Caddy 自动续期。不要删除历史镜像或 `releases` 目录，否则历史版本回滚可能失去必要产物；也不要把 `docker compose ... up` 用作新发布系统的日常操作，它可能重新启动已停用的旧后端。

日常维护应检查磁盘容量，备份和旧镜像目前不自动清理。每日备份默认只保存在 ECS，后续应按实际需要配置异地备份。

## 本地验证

```sh
# 发布失败恢复、版本校验、worker 顺序等单元测试。
backend/.venv/bin/python -m unittest discover -s deploy/tests -v

# 后端测试显式使用隔离 SQLite，不连接生产 MySQL。
cd backend
APP_DATABASE_MODE=sqlite .venv/bin/python -m unittest discover -s tests -v
cd ..

# 构建与 ECS 架构一致的镜像（Docker Hub 不通时可用 Dockerfile 中的镜像 ARG 换源）。
docker build --platform linux/amd64 -f deploy/Dockerfile.backend -t knowledge-base-release-test:backend .
docker build --platform linux/amd64 -f deploy/Dockerfile.release-frontend -t knowledge-base-release-test:frontend .

# 预先准备仅供隔离测试的 MySQL 镜像。
docker pull mysql:8.4

# 演练新旧版分流、promote、指定版本 rollback、abort、schema 拒绝；结束清理测试容器。
backend/.venv/bin/python deploy/tests/integration_release.py
```
