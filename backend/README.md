# Knowledge Workspace API

Python 3.11+ / FastAPI / SQLAlchemy / SQLite。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip3 install -e .
APP_PORT=8001 python3 run.py
```

API 分组：

- `/api/knowledge/bases`：知识库管理、库内资料导入与切片。
- `/api/knowledge/search`、`/api/knowledge/ask`：限定知识库的检索与问答。
- `/api/ai/providers`、`/api/ai/models`、`/api/ai/chat`：模型配置与调用。
- `/api/usage`、`/api/usage/export`：Token 汇总、趋势、模型分布、分页明细及 CSV。

运行回归测试（不访问付费模型）：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

配置、统计口径、数据库迁移及版本边界见 [项目说明](../README.md)。

生产部署、首次登录、人才管理与去重导入见 [实施与验收](../docs/production-implementation.md)。新上传接口 `/api/imports/{knowledge_base_id}` 返回持久任务，`/api/jobs` 查询任务；`/api/talents` 提供结构化人才管理。
