# Knowledge Base

Vue + FastAPI knowledge base starter. The first implementation focuses on a usable document workspace and a configurable model-provider layer that can later power summarization, semantic search and RAG.

## Current Shape

```text
.
├── backend/                 # FastAPI API scaffold with SQLite persistence
│   └── app/
│       ├── ai/              # Provider registry and adapters
│       ├── api/routes/      # Documents, categories and AI config APIs
│       ├── core/            # Settings
│       ├── db/              # SQLAlchemy session, ORM models and seed bootstrap
│       ├── repositories/    # SQLite-backed repositories
│       └── schemas/         # Pydantic contracts
└── frontend/                # Vue 3 + Vite frontend app
    ├── src/
    │   ├── App.vue          # Knowledge base workspace shell
    │   └── lib/             # Frontend types, seed data and markdown renderer
    └── package.json
```

## Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

Use a custom backend URL when needed:

```bash
cd frontend
VITE_API_BASE_URL=http://127.0.0.1:8001/api pnpm dev
```

Backend model config is injected by environment variables:

```bash
APP_PORT=8001
AGENT_DEFAULT_API_URL=https://your-openai-compatible-endpoint/v1
AGENT_DEFAULT_API_KEY=your-api-key
AGENT_DEFAULT_MODEL=qwen-plus
AGENT_EMBEDDING_API_URL=https://your-openai-compatible-embedding-endpoint/v1
AGENT_EMBEDDING_API_KEY=your-embedding-api-key
AGENT_EMBEDDING_MODEL=text-embedding-v3
```

The current frontend includes:

- document list, search and category filter
- document editor and Markdown preview
- backend-backed document creation/deletion with local demo fallback
- model provider configuration panel
- provider switching and model registration UI

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
APP_PORT=8001 python run.py
```

API base URL:

```text
http://localhost:8001/api
```

Included API groups:

- `/api/documents`
- `/api/categories`
- `/api/ai/providers`
- `/api/ai/models`
- `/api/ai/chat`

SQLite is used by default:

```text
backend/knowledge_base.db
```

Override it with `DATABASE_URL` in `backend/.env`.
You can also set `APP_UPLOAD_DIR` and the default model config above in `backend/.env`.

Knowledge retrieval uses hybrid scoring when embedding config is present:

```text
hybrid_score = lexical_score * APP_KB_HYBRID_LEXICAL_WEIGHT
             + embedding_score * APP_KB_HYBRID_EMBEDDING_WEIGHT
```

If embedding config is missing or an embedding request fails, the backend falls back to lexical retrieval.

Schema migrations are scaffolded with Alembic:

```bash
cd backend
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

## AI Provider Design

Model calls are intentionally isolated behind `backend/app/ai`.

```text
backend/app/ai/
├── base.py
├── registry.py
└── providers/
    ├── mock.py
    └── openai_compatible.py
```

Business code should call the registry instead of a provider SDK directly. To add a real provider later:

1. Add an adapter in `backend/app/ai/providers/`.
2. Register it in `backend/app/ai/registry.py`.
3. Add or update provider config through `/api/ai/providers`.
4. Switch default provider through `/api/ai/providers/{provider_id}/switch`.

`mock` is enabled by default so the app can be developed without a live model API key.

## Next Implementation Steps

1. Add auth and route guards.
2. Add attachments and document version history.
3. Implement live OpenAI-compatible chat calls and encrypted API key storage.
4. Add semantic search and RAG over published documents.
