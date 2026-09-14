# Knowledge Workspace API

Python 3.11+ / FastAPI / SQLAlchemy / SQLite。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
APP_PORT=8001 python run.py
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
