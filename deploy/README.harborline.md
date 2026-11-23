# 通过航站平台发布知识库前端

首次将 `.github/workflows/harborline-build.yml` 与更新后的 `frontend-e2e.yml` 一并提交到默认分支和发布分支。在航站「项目管理 → 发布配置」填写仓库、main 分支、harborline-build.yml、前置 CI frontend-ci.yml、Dockerfile deploy/Dockerfile.frontend、构建目录 .、实际服务器架构，以及 VITE_APP_VERSION={version}。GitHub Token 仅填写在平台配置中，需要目标仓库 Contents 读取和 Actions 读写权限。

再配置一次三个环境的节点、端口、API_UPSTREAM、Docker 网络与测试镜像。之后 test 直接点击发布，平台自动等待源码 CI、触发镜像构建和完整 E2E、下载校验镜像并部署测试；pre/pro 复用同一份已通过上游测试的制品。

新工作流不执行 SSH 部署或创建 GitHub Release。旧 frontend-release.yml 保持原有用途，使用航站日常发布时不要同时触发旧生产部署流水线。

运行时镜像仍只包含前端；后端、数据库由既有部署方式维护。镜像中的版本号由平台传入，可自动生成；不要求修改 frontend/package.json 的版本。

## ACR 镜像入库

知识库已配置个人版仓库：
`crpi-dy2oreopori9tcld.cn-shanghai.personal.cr.aliyuncs.com/wangbo-deploy/knowledge-base-frontend`。
登录名 `aliyun5531032824`；Registry 密码仅保存为此 GitHub 仓库的 Repository Secret `ACR_PASSWORD`。

Harborline Build 的 publish job 等待 build 和完整 E2E 全部成功后，下载同一次构建的归档，校验请求/版本/提交与 SHA-256，再通过 password-stdin 登录 ACR。镜像标签包含版本、提交和请求 ID；发布清单使用 `repository@sha256:...` 固定镜像身份。密码不进入构建输入、镜像或制品清单。

平台「发布配置」填写镜像仓库地址和登录名后，会自动传给工作流，并接收 `harborline-registry-<request_id>` 小型清单，而非下载整个镜像归档。其他项目可以复用部署平台的工作流模板，配置各自的仓库与 ACR_PASSWORD。

本工作流只做 CI/E2E/镜像推送，不执行 SSH 部署或服务器上的浏览器测试。服务器拉取凭据、SSH/Compose 部署与首次入口切换需要在服务器恢复并确认资源后接入；当前不能把 ACR 入库完成视为整条生产部署链路已经恢复。

为防止通过手动输入其他 Registry 地址诱导工作流发送密码，知识库工作流在登录前只允许上面明确配置的仓库。更换仓库需同步修改工作流的 APPROVED_REGISTRY_REPOSITORY。通用模板使用仓库变量 ACR_REPOSITORY 作为可信白名单，需由仓库管理员首次设置；不能用 dispatch 输入替代白名单。
