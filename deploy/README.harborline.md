# 通过航站平台发布知识库前端

首次将 `.github/workflows/harborline-build.yml` 与更新后的 `frontend-e2e.yml` 一并提交到默认分支和发布分支。在航站「项目管理 → 发布配置」填写仓库、main 分支、harborline-build.yml、前置 CI frontend-ci.yml、Dockerfile deploy/Dockerfile.frontend、构建目录 .、实际服务器架构，以及 VITE_APP_VERSION={version}。GitHub Token 仅填写在平台配置中，需要目标仓库 Contents 读取和 Actions 读写权限。

再配置一次三个环境的节点、端口、API_UPSTREAM、Docker 网络与测试镜像。之后 test 直接点击发布，平台自动等待源码 CI、触发镜像构建和完整 E2E、下载校验镜像并部署测试；pre/pro 复用同一份已通过上游测试的制品。

新工作流不执行 SSH 部署或创建 GitHub Release。旧 frontend-release.yml 保持原有用途，使用航站日常发布时不要同时触发旧生产部署流水线。

运行时镜像仍只包含前端；后端、数据库由既有部署方式维护。镜像中的版本号由平台传入，可自动生成；不要求修改 frontend/package.json 的版本。
