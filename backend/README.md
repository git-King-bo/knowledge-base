# Knowledge Base Backend

FastAPI backend scaffold for the knowledge base.

## Run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
APP_PORT=8001 python run.py
```

Optional model config:

```bash
AGENT_DEFAULT_API_URL=https://your-openai-compatible-endpoint/v1
AGENT_DEFAULT_API_KEY=your-api-key
AGENT_DEFAULT_MODEL=qwen-plus
AGENT_EMBEDDING_API_URL=https://your-openai-compatible-embedding-endpoint/v1
AGENT_EMBEDDING_API_KEY=your-embedding-api-key
AGENT_EMBEDDING_MODEL=text-embedding-v3
APP_UPLOAD_DIR=storage/uploads
```

Hybrid retrieval is enabled automatically when `AGENT_EMBEDDING_API_URL` and `AGENT_EMBEDDING_MODEL` are set. The embedding API should be OpenAI-compatible and expose `/embeddings`.

SQLite is used by default through SQLAlchemy. The database file is created at `backend/knowledge_base.db` when the app starts.

Alembic is available for controlled schema changes:

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```
