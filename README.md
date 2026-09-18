# 知序 · 知识工作空间

Vue 3 + TypeScript + FastAPI + SQLite 的本地知识库产品。围绕「建立知识库 → 导入与切片 → 检索验证 → 引用问答 → Token 监控」组织工作流程。

## 产品模块

- **知识库**：创建、编辑、标签、搜索、归档、恢复与删除；库内批量导入资料、查看处理错误、预览切片和重建向量索引。
- **检索测试**：指定知识库、调整 Top K（1–12），查看命中片段、来源与相关度。
- **知识问答**：选择模型服务，流式生成带来源的答案，支持停止及继续生成，保留部分内容；支持按需补充联网搜索、Markdown、代码高亮。
- **Token 监控**：输入、输出、缓存命中、总用量、调用次数、失败数、耗时、覆盖率、按日趋势和模型分布；按 1/7/30/90 天、服务、模型、类型、知识库筛选，明细分页和 CSV 导出。
- **模型配置**：新增/编辑兼容服务、切换默认服务、连接测试和模型试用。

独立文档编辑和分类模块已移除，资料统一放在知识库中。旧文档数据表保留以避免丢失原有数据，但不再提供对应界面和 API。前端没有伪造数据或离线演示回退。

## 本地运行

后端需要 Python 3.11+：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
# 可将 .env.example 复制为 .env 并配置模型
APP_PORT=8001 python run.py
```

前端：

```bash
cd frontend
pnpm install
pnpm dev
```

默认地址为 `http://127.0.0.1:5174`；端口被占用时 Vite 会选择下一个可用端口。可用 `VITE_PORT`、`VITE_HOST` 调整；`VITE_API_BASE_URL` 默认为 `http://127.0.0.1:8001/api`。

## 模型、检索与导入

可在模型配置页面添加服务，也可在 `backend/.env` 首次初始化默认服务：

```dotenv
AGENT_DEFAULT_API_URL=https://your-provider.example/v1
AGENT_DEFAULT_API_KEY=your-key
AGENT_DEFAULT_MODEL=your-model
AGENT_EMBEDDING_API_URL=https://your-provider.example/v1
AGENT_EMBEDDING_API_KEY=your-key
AGENT_EMBEDDING_MODEL=your-embedding-model
APP_KB_CHUNK_MAX_CHARS=480
APP_KB_CHUNK_OVERLAP_CHARS=80
```

模型服务初始化后，页面保存的地址、模型和默认服务选择会保留；环境密钥用于环境默认服务未单独保存密钥时的回退。Mock 仅用于本地连通性验证。

资料支持 TXT、Markdown、PDF、DOCX、XLSX、CSV、JSON，每份最多 20 MB；扫描 PDF 需先 OCR。XLSX 会读取所有非空工作表，保留工作表名和行内单元格顺序；公式读取文件中缓存的计算结果，不执行重算，含公式的文件请先在 Excel 中计算并保存后上传。旧版 XLS 需另存为 XLSX 或 CSV。解析及索引在当前请求中完成。缺少向量化配置时使用词法检索；向量化调用失败时记录失败并回退到词法检索。归档知识库不会参与检索。

XLSX 总数类问题会额外读取当前知识库的原始工作簿，按工作表提供完整行数统计，不受检索切片数量限制，已上传文件无需重新导入。首个非空行为包含“姓名”等字段的表头时，统计姓名非空的记录数及不同姓名文本数；同名不代表同一身份，记录数不等于按身份去重的人数。当前统计不执行按部门等条件筛选，也不跨文件合并去重；原文件缺失时明确无法确认总数。

资料列表的“预览”可查看文件内容：XLSX/CSV 每页展示 50 个非空行、原始行号，XLSX 支持工作表切换；最多展示前 200 列，超出时给出提示。PDF 使用浏览器原文预览；DOCX、TXT、Markdown、JSON 展示分页正文文本，DOCX 不保留原始排版。预览独立于检索切片，接口校验资料与当前知识库的关联。

联网搜索沿用 `WEB_SEARCH_ENABLED`、`WEB_SEARCH_PROVIDER`、`WEB_SEARCH_API_KEY` 等配置。未配置或搜索失败时，回答仅使用可用的知识库来源。

人才 XLSX 查询保留完整人员行与列名，按领域、机构等字段筛选，并支持明确来源的数值指标排序，例如“具身智能领域按 OpenAlex h-index 排名前20”。常见领域及指标查询直接执行，其他条件由当前模型生成受字段白名单约束的查询计划（检索测试使用默认模型），程序执行 AND 筛选及数值排序，不运行生成代码。自然语言规划会额外计入一次模型调用。缺失或非数值指标不参与排名；展示数量遵守页面召回数量 Top K（默认5），所有文件合计不超过该上限；问题要求更少时取更小值，附全表命中数、缺失数和原始行号。各文件独立统计，排序后统一限制展示数量，现有文件无需重新导入；OR、分组等暂不支持的复杂条件会要求明确查询。

## 流式问答

`POST /api/knowledge/ask/stream` 使用 fetch 接收 SSE，依次返回 `meta`（来源）、`delta`（正文）和 `done`（用量）；中途失败返回 `error`。模型服务需支持兼容 OpenAI 的流式接口和 `stream_options.include_usage`，未报告的用量保持未知。原非流式接口保留。停止或中断后可在原回答下点击「继续生成」，沿用原模型、问题和来源快照，将已生成正文作为 assistant 上下文发起新请求，新增内容接到原回答；每次续写单独记录实际用量。这是模型续写请求，不能恢复供应商已取消的连接。

前端通过 `setApiHeaders(() => ({ Authorization: 'Bearer app-session' }))` 设置动态公共请求头；`streamKnowledge(payload, { headers, signal, onMeta, onDelta })` 支持单次覆盖及取消。应用会话请求头与后端模型 API 密钥分开管理。

正文先缓冲，再由 `requestAnimationFrame` 每帧最多解析一次完整 Markdown 快照。未闭合标记随后续内容补全，代码高亮在结束时执行。原始 HTML 转为文本，最终 HTML 经过 DOMPurify 白名单清洗；链接限 HTTP/HTTPS，Markdown 图片显示为链接，Chunk/Web 引用保留点击定位。

## Token 统计口径

- 模型适配器返回 `ChatResult(content, usage)`；问答、模型试用及每批向量化请求都会保存调用记录。
- 用量来自服务响应的 `usage`。只在输入和输出都已报告时相加补齐缺失的总量，不按文本长度推算费用或用量。
- 缓存命中属于输入 Token，不再加入总量。
- 原有日志缺少用量时显示未知；Mock 和失败且未返回用量的请求也不计入已报告 Token 总量。
- 汇总与图表覆盖筛选范围内全部记录，明细分页不会截断汇总。时间以 UTC 存储，按浏览器本地时区划分日期。
- 切片中的本地词元估算用于内容处理，与模型实际消耗不同。
- 平台统计本项目发起的调用，不是整个供应商账户账单；联网搜索服务的额外费用和货币成本不在统计范围内。

## 项目结构

```text
frontend/src/
  App.vue                  # 导航与工作空间状态
  views/                   # 知识库、检索/问答、用量、模型设置
  components/              # 图标、可访问对话框
  composables/useTask.ts   # 操作状态与错误处理
  lib/                     # API、类型、用量契约、Markdown
backend/app/
  ai/                      # 模型适配器，保留真实 usage
  api/routes/              # knowledge、ai、usage
  services/                # 解析、切片、向量化、联网搜索
  repositories/            # SQLite 持久化与检索
  db/                      # ORM 与数据库初始化
  schemas/                 # 请求和响应契约
backend/tests/             # 隔离数据库的流程与统计回归测试
```

## 数据库与验证

默认数据库为 `backend/knowledge_base.db`。启动会增量创建缺失表，不回填历史用量、不删除旧数据。

全新数据库可使用 `alembic upgrade head`。如果已有数据库由旧版应用自动创建且从未使用 Alembic，应先备份并确认与 `0001_initial` 的四张旧表一致，再执行 `alembic stamp 0001_initial` 和 `alembic upgrade head`。不要直接对已有未标记数据库执行首个建表迁移。

```bash
cd frontend
npm test
npm run build

cd ../backend
.venv/bin/python -m unittest discover -s tests -v
```

当前为单工作空间、本地部署版本。尚未实现多租户权限、后台导入任务队列和模型密钥加密存储；不要将当前实例直接作为公网多用户服务。
