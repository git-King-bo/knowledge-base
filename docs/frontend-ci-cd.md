# 前端 CI/CD、E2E 与自动发版

本流水线只交付 Vue 前端。E2E 拦截全部 API，拒绝未声明请求和外网访问；不启动后端、数据库或模型服务。旧 `ci.yaml` 只保留后端检查，前端检查没有重复入口。

## 触发与门禁

| 入口 | 触发 | 执行顺序 |
| --- | --- | --- |
| Frontend CI | PR 到 main、push main | 变更识别 → 部署脚本回归 → 类型 → 单元/组件 → 生产构建 |
| Frontend E2E | 被其他工作流调用 | main 使用构建产物跑 `@smoke`；发版使用最终镜像跑全部用例 |
| Frontend Release | 在 main 手动输入版本 | 验证 SHA 已通过 main CI → 快检查 → 镜像构建 → 完整 E2E → web 部署 → 生产检查 → Tag/Release |

PR 不下载浏览器、不构建镜像。main 只有前端、前端部署或工作流配置变化才运行冒烟。纯后端/文档改动仍产生 `frontend-required` 成功状态。PR 的旧运行会被新提交取消；生产发布串行，进行中的发布不取消。GitHub 默认只保留一个待执行的并发运行，密集提交多个发布请求可能替换待执行请求；请一次完成一个版本。

仓库 main 分支规则应要求 `frontend-required`，不要绑定可跳过的 `quick` 或 `smoke`。建议要求 PR 合并、禁止强推，并限制 `frontend-*` Tag 的人工修改。当前未接入 merge queue；启用它前需补充 `merge_group` 事件。

## 本地命令

在 frontend 目录执行：

```bash
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build:assets
pnpm exec playwright install chromium
pnpm test:e2e:smoke
pnpm test:e2e
```

E2E 默认自动启动 `vite preview`，只访问本地 `127.0.0.1:4173`。必须先构建；不要使用 `dev:online`。`E2E_BASE_URL` 仅用于让测试访问已经启动的前端镜像。API 固定响应只存在于 `e2e/`，不打包到应用。减少动态效果采用浏览器标准配置，不添加生产测试开关。

冒烟覆盖登录/退出、知识库过滤与详情、创建、检索和跨导航状态。完整套件增加错误重试、只读入口、空状态、未提交输入更新保护、上传确认、固定 SSE 与 Markdown 展示。它不证明后端权限或真实接口可用性。版本保护目前覆盖非模态的登录输入；知识库原生模态弹窗打开时，更新提示会受模态层交互限制，本次未修改业务 UI。

CI 最多重试一次，重试通过仍按 flaky 失败处理；失败截图、trace 和 HTML 报告保留 7 天。单元测试沿用现有 runner；测试类型也进入 typecheck。

部署脚本隔离回归：

```bash
python3 -m unittest discover -s deploy/tests -v
```

这些测试使用临时目录和模拟 Docker，覆盖前端独立更新、健康检查失败回滚、外部检查失败后回滚及拒绝过期回滚，不操作真实容器。

## 首次启用配置

在 GitHub 仓库 Settings → Environments 创建 `frontend-production`，仅允许 main 部署。是否启用人工审批由团队决定；流水线本身不强制审批。

环境 Variables：

| 名称 | 内容 |
| --- | --- |
| `FRONTEND_SSH_HOST` | 服务器域名或 IPv4，GitHub 托管 runner 必须能访问 |
| `FRONTEND_SSH_USER` | 部署账号 |
| `FRONTEND_SSH_PORT` | 可选，默认 22 |
| `FRONTEND_PUBLIC_URL` | 前端根地址，例如 `https://kb.example.com`，不带查询参数 |

环境 Secrets：

| 名称 | 内容 |
| --- | --- |
| `FRONTEND_SSH_KEY` | 部署账号专用 SSH 私钥 |
| `FRONTEND_SSH_KNOWN_HOSTS` | 已通过可信渠道核对的服务器 host key；非标准端口使用 `[host]:port` 格式 |

前提：服务器已有正常运行的 `/opt/knowledge-base` company 部署，含 `deploy/compose.company.yaml`、`deploy/company-version.env`、运行中的 web 容器；Compose web 镜像格式沿用 `knowledge-company-frontend:${KB_FRONTEND_VERSION}`，并挂载 `data/frontend-assets`。需要支持 `--wait` 的 Docker Compose、Bash、curl、flock、sha256sum、sed、awk；部署账号须能操作 Docker 和项目目录。此工作流不负责首次初始化服务器，也不修改 Nginx、MySQL 配置或后端。

## 发布操作

1. 等待目标 main 提交的 Frontend CI 成功。
2. Actions → Frontend Release → Run workflow，分支选 main，输入 `0.2.0` 等三段数字版本。
3. 工作流固定本次 main SHA；main 后续变化不会改变这次发布内容。
4. 快检查通过后只构建一次 amd64 镜像，生成镜像 ID、发布清单和 SHA-256 校验值。
5. 完整 E2E 对该镜像运行；成功后上传同一镜像，服务器校验后仅更新 web。
6. 本机和公开地址检查首页、JS/CSS 的内容类型与非空内容、`version.json` 精确版本；runner 再从外部检查公开地址。
7. 成功后创建 `frontend-v0.2.0` Tag 和 GitHub Release，附发布清单、校验文件。完整镜像包存于对应 Actions artifact，保留 14 天。

前端实际版本为 `frontend-v0.2.0-<12位SHA>`，同步写入 `VITE_APP_VERSION` 和部署状态。frontend/package.json 的版本不用于发布，不需要机器人提交版本变更。GitHub Release 是前端发布记录，不发布 npm 包。

生产密钥只在部署 job 可用。PR 只读；创建 Tag/Release 的独立 job 才拥有 contents:write。不依赖 Tag 事件二次触发工作流。

## 失败与恢复

- 快检查或 E2E 失败：不会接触生产。
- 部署前失败：现有 web 保持原状。
- 镜像更新后健康检查失败：恢复之前的前端版本配置和镜像；旧哈希静态资源继续保留。
- runner 外部检查失败：通过 SSH 请求同一次部署回滚；若 SSH 已不可达，自动回滚也可能失败，需人工查看该 run 日志并在服务器执行恢复。
- 服务器端更新和回滚共用现有 `deploy.lock`，避免与旧运维脚本并发。回滚检查当前版本，拒绝覆盖已经更新到其他版本的服务。
- 已部署但 Release 创建失败：使用 Actions 的 **Re-run failed jobs**，只补齐发布记录。
- E2E 或部署失败同样优先 **Re-run failed jobs**，复用已有发布包；不要对同一版本重跑全部构建。服务器拒绝相同镜像 Tag 对应不同镜像 ID。
- 版本已有正式 Tag 时拒绝重复创建版本。不自动删除旧镜像与哈希静态资源；清理时必须保留当前和可回滚版本。

回滚材料位于 `/opt/knowledge-base/incoming/<前端版本>-<run_id>/`，含 `previous-version.env`、`previous-image-id` 和可能存在的旧 manifest。正式手动回滚可在该目录使用本次发布的参数执行 `bash frontend-apply.sh <前端版本> <公开地址> <本次镜像ID> rollback`。保留此目录直到版本不再需要回滚。
