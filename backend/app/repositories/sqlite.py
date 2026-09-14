import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AIActivityLogModel,
    TokenUsageModel,
    AIModelModel,
    AIProviderModel,
    KnowledgeBaseModel,
    KnowledgeBaseSourceModel,
    KnowledgeChunkEmbeddingModel,
    KnowledgeChunkModel,
    KnowledgeSourceModel,
)
from app.schemas.ai import ProviderConfig, ProviderCreate, ProviderModel, ProviderModelCreate, ProviderUpdate
from app.schemas.usage import TokenUsage
from app.schemas.knowledge import (
    AIActivityLog,
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeChunk,
    KnowledgeSource,
)

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def _tags_to_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _tags_to_text(value: list[str]) -> str:
    return ",".join(item.strip() for item in value if item.strip())


def _provider_from_model(model: AIProviderModel) -> ProviderConfig:
    return ProviderConfig(
        id=model.id,
        name=model.name,
        provider=model.provider,
        base_url=model.base_url,
        api_key_hint=model.api_key_hint,
        default_model=model.default_model,
        is_default=model.is_default,
    )


def _model_from_model(model: AIModelModel) -> ProviderModel:
    return ProviderModel(
        id=model.id,
        provider_id=model.provider_id,
        name=model.name,
        context_window=model.context_window,
        supports_tools=model.supports_tools,
        supports_vision=model.supports_vision,
        status=model.status,  # type: ignore[arg-type]
    )


def _api_key_from_model(model: AIProviderModel) -> str | None:
    if not model.api_key_encrypted and model.id == "provider-agent-default" and settings.default_api_key:
        return settings.default_api_key
    return model.api_key_encrypted or None


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _vectorize(text: str) -> dict[str, int]:
    return dict(Counter(_tokenize(text)))


def _dot(a: dict[str, int], b: dict[str, int]) -> float:
    keys = a.keys() & b.keys()
    return float(sum(a[key] * b[key] for key in keys))


def _norm(vector: dict[str, int]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _cosine_similarity(a: dict[str, int], b: dict[str, int]) -> float:
    denominator = _norm(a) * _norm(b)
    if denominator == 0:
        return 0.0
    return _dot(a, b) / denominator


def _dense_cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(left * right for left, right in zip(a, b))
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    denominator = norm_a * norm_b
    if denominator == 0:
        return 0.0
    return dot / denominator


def _chunk_to_schema(model: KnowledgeChunkModel, score: float | None = None) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=model.id,
        source_id=model.source_id,
        chunk_index=model.chunk_index,
        title=model.title,
        content=model.content,
        token_count=model.token_count,
        score=score,
    )


def _source_to_schema(model: KnowledgeSourceModel) -> KnowledgeSource:
    return KnowledgeSource(
        id=model.id,
        filename=model.filename,
        mime_type=model.mime_type,
        status=model.status,  # type: ignore[arg-type]
        chunk_count=model.chunk_count,
        error_message=model.error_message,
        created_at=model.created_at,
    )


def _knowledge_base_to_schema(model: KnowledgeBaseModel, source_count: int = 0, chunk_count: int = 0) -> KnowledgeBase:
    return KnowledgeBase(
        id=model.id,
        name=model.name,
        description=model.description,
        tags=_tags_to_list(model.tags),
        status=model.status,  # type: ignore[arg-type]
        source_count=source_count,
        chunk_count=chunk_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _log_to_schema(model: AIActivityLogModel) -> AIActivityLog:
    return AIActivityLog(
        id=model.id,
        action=model.action,  # type: ignore[arg-type]
        provider_id=model.provider_id,
        model=model.model,
        success=model.success,
        latency_ms=model.latency_ms,
        request_text=model.request_text,
        response_text=model.response_text,
        created_at=model.created_at,
    )


class AIRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_providers(self) -> list[ProviderConfig]:
        models = self.db.scalars(select(AIProviderModel).order_by(AIProviderModel.name)).all()
        return [_provider_from_model(item) for item in models]

    def get_provider(self, provider_id: str) -> ProviderConfig | None:
        model = self.db.get(AIProviderModel, provider_id)
        return _provider_from_model(model) if model else None

    def get_provider_credentials(self, provider_id: str) -> tuple[ProviderConfig, str | None] | None:
        model = self.db.get(AIProviderModel, provider_id)
        if not model:
            return None
        return _provider_from_model(model), _api_key_from_model(model)

    def get_default_provider(self) -> ProviderConfig:
        model = self.db.scalar(select(AIProviderModel).where(AIProviderModel.is_default.is_(True)))
        if not model:
            model = self.db.scalar(select(AIProviderModel).limit(1))
        if not model:
            raise RuntimeError("No AI provider configured")
        return _provider_from_model(model)

    def get_default_provider_credentials(self) -> tuple[ProviderConfig, str | None]:
        model = self.db.scalar(select(AIProviderModel).where(AIProviderModel.is_default.is_(True)))
        if not model:
            model = self.db.scalar(select(AIProviderModel).limit(1))
        if not model:
            raise RuntimeError("No AI provider configured")
        return _provider_from_model(model), _api_key_from_model(model)

    def create_provider(self, payload: ProviderCreate) -> ProviderConfig:
        has_key = bool(payload.api_key and payload.api_key.get_secret_value())
        is_first = self.db.scalar(select(func.count(AIProviderModel.id))) == 0
        model = AIProviderModel(
            id=str(uuid4()),
            name=payload.name,
            provider=payload.provider,
            base_url=payload.base_url,
            api_key_encrypted=payload.api_key.get_secret_value() if payload.api_key else "",
            api_key_hint="已填写" if has_key else "未填写",
            default_model=payload.default_model,
            is_default=is_first,
        )
        self.db.add(model)
        self.db.add(
            AIModelModel(
                id=str(uuid4()),
                provider_id=model.id,
                name=model.default_model,
                context_window=32000,
                supports_tools=False,
                supports_vision=False,
                status="draft",
            )
        )
        self.db.commit()
        self.db.refresh(model)
        return _provider_from_model(model)

    def update_provider(self, provider_id: str, payload: ProviderUpdate) -> ProviderConfig | None:
        model = self.db.get(AIProviderModel, provider_id)
        if not model:
            return None

        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        if updates.get("is_default") is True:
            self._clear_default_provider()
        if "api_key" in updates:
            api_key = updates.pop("api_key")
            model.api_key_encrypted = api_key.get_secret_value() if api_key else ""
            model.api_key_hint = "已填写" if api_key else "未填写"

        for key, value in updates.items():
            setattr(model, key, value)

        self.db.commit()
        self.db.refresh(model)
        return _provider_from_model(model)

    def switch_default_provider(self, provider_id: str) -> ProviderConfig | None:
        model = self.db.get(AIProviderModel, provider_id)
        if not model:
            return None
        self._clear_default_provider()
        model.is_default = True
        self.db.commit()
        self.db.refresh(model)
        return _provider_from_model(model)

    def list_models(self, provider_id: str | None = None) -> list[ProviderModel]:
        statement = select(AIModelModel).order_by(AIModelModel.name)
        if provider_id:
            statement = statement.where(AIModelModel.provider_id == provider_id)
        return [_model_from_model(item) for item in self.db.scalars(statement).all()]

    def create_model(self, provider_id: str, payload: ProviderModelCreate) -> ProviderModel | None:
        if not self.db.get(AIProviderModel, provider_id):
            return None
        model = AIModelModel(provider_id=provider_id, id=str(uuid4()), **payload.model_dump())
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return _model_from_model(model)

    def _clear_default_provider(self) -> None:
        for item in self.db.scalars(select(AIProviderModel)).all():
            item.is_default = False

    def create_activity_log(
        self,
        *,
        action: str,
        provider_id: str,
        model: str,
        request_text: str,
        response_text: str,
        success: bool,
        latency_ms: int,
        usage: TokenUsage | None = None,
        knowledge_base_id: str | None = None,
    ) -> AIActivityLog:
        record = AIActivityLogModel(
            id=str(uuid4()),
            action=action,
            provider_id=provider_id,
            model=model,
            request_text=request_text,
            response_text=response_text,
            success=success,
            latency_ms=latency_ms,
            created_at=_now(),
        )
        self.db.add(record)
        self.db.flush()
        self.db.add(TokenUsageModel(log_id=record.id, knowledge_base_id=knowledge_base_id,
                                    **(usage or TokenUsage()).model_dump()))
        self.db.commit()
        self.db.refresh(record)
        return _log_to_schema(record)

    def list_activity_logs(self, limit: int = 100) -> list[AIActivityLog]:
        rows = self.db.scalars(
            select(AIActivityLogModel).order_by(AIActivityLogModel.created_at.desc()).limit(limit)
        ).all()
        return [_log_to_schema(item) for item in rows]


class KnowledgeIngestionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _knowledge_base_counts(self, knowledge_base_id: str) -> tuple[int, int]:
        rows = self.db.execute(
            select(KnowledgeSourceModel.chunk_count)
            .join(KnowledgeBaseSourceModel, KnowledgeBaseSourceModel.source_id == KnowledgeSourceModel.id)
            .where(KnowledgeBaseSourceModel.knowledge_base_id == knowledge_base_id)
        ).all()
        return len(rows), sum(chunk_count or 0 for (chunk_count,) in rows)

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        rows = self.db.scalars(
            select(KnowledgeBaseModel).order_by(KnowledgeBaseModel.updated_at.desc(), KnowledgeBaseModel.name.asc())
        ).all()
        result: list[KnowledgeBase] = []
        for item in rows:
            source_count, chunk_count = self._knowledge_base_counts(item.id)
            result.append(_knowledge_base_to_schema(item, source_count=source_count, chunk_count=chunk_count))
        return result

    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None:
        model = self.db.get(KnowledgeBaseModel, knowledge_base_id)
        if not model:
            return None
        source_count, chunk_count = self._knowledge_base_counts(model.id)
        return _knowledge_base_to_schema(model, source_count=source_count, chunk_count=chunk_count)

    def create_knowledge_base(self, payload: KnowledgeBaseCreate) -> KnowledgeBase:
        record = KnowledgeBaseModel(
            id=str(uuid4()),
            name=payload.name,
            description=payload.description,
            tags=_tags_to_text(payload.tags),
            status="active",
            created_at=_now(),
            updated_at=_now(),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return _knowledge_base_to_schema(record)

    def update_knowledge_base(self, knowledge_base_id: str, payload: KnowledgeBaseUpdate) -> KnowledgeBase | None:
        record = self.db.get(KnowledgeBaseModel, knowledge_base_id)
        if not record:
            return None
        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "tags" in updates and updates["tags"] is not None:
            updates["tags"] = _tags_to_text(updates["tags"])
        for key, value in updates.items():
            setattr(record, key, value)
        record.updated_at = _now()
        self.db.commit()
        self.db.refresh(record)
        source_count, chunk_count = self._knowledge_base_counts(record.id)
        return _knowledge_base_to_schema(record, source_count=source_count, chunk_count=chunk_count)

    def delete_knowledge_base(self, knowledge_base_id: str) -> bool:
        record = self.db.get(KnowledgeBaseModel, knowledge_base_id)
        if not record:
            return False
        self.db.delete(record)
        self.db.commit()
        return True

    def attach_source_to_base(self, knowledge_base_id: str, source_id: str) -> None:
        exists = self.db.scalar(
            select(KnowledgeBaseSourceModel).where(
                KnowledgeBaseSourceModel.knowledge_base_id == knowledge_base_id,
                KnowledgeBaseSourceModel.source_id == source_id,
            )
        )
        if exists:
            return
        self.db.add(
            KnowledgeBaseSourceModel(
                id=str(uuid4()),
                knowledge_base_id=knowledge_base_id,
                source_id=source_id,
                created_at=_now(),
            )
        )
        base = self.db.get(KnowledgeBaseModel, knowledge_base_id)
        if base:
            base.updated_at = _now()
        self.db.commit()

    def detach_source_from_base(self, knowledge_base_id: str, source_id: str) -> KnowledgeBase | None:
        base = self.db.get(KnowledgeBaseModel, knowledge_base_id)
        if not base:
            return None
        links = self.db.scalars(
            select(KnowledgeBaseSourceModel).where(
                KnowledgeBaseSourceModel.knowledge_base_id == knowledge_base_id,
                KnowledgeBaseSourceModel.source_id == source_id,
            )
        ).all()
        if not links:
            return self.get_knowledge_base(knowledge_base_id)
        for link in links:
            self.db.delete(link)
        base.updated_at = _now()
        self.db.commit()
        self.db.refresh(base)
        source_count, chunk_count = self._knowledge_base_counts(base.id)
        return _knowledge_base_to_schema(base, source_count=source_count, chunk_count=chunk_count)

    def list_base_sources(self, knowledge_base_id: str) -> list[KnowledgeSource]:
        rows = self.db.scalars(
            select(KnowledgeSourceModel)
            .join(KnowledgeBaseSourceModel, KnowledgeBaseSourceModel.source_id == KnowledgeSourceModel.id)
            .where(KnowledgeBaseSourceModel.knowledge_base_id == knowledge_base_id)
            .order_by(KnowledgeBaseSourceModel.created_at.desc())
        ).all()
        return [_source_to_schema(item) for item in rows]

    def list_base_chunks(self, knowledge_base_id: str) -> list[KnowledgeChunk]:
        rows = self.db.scalars(
            select(KnowledgeChunkModel)
            .join(KnowledgeBaseSourceModel, KnowledgeBaseSourceModel.source_id == KnowledgeChunkModel.source_id)
            .where(KnowledgeBaseSourceModel.knowledge_base_id == knowledge_base_id)
            .order_by(KnowledgeChunkModel.created_at.desc(), KnowledgeChunkModel.chunk_index.asc())
        ).all()
        return [_chunk_to_schema(item) for item in rows]

    def create_source(self, *, filename: str, mime_type: str, storage_path: str, content_text: str) -> KnowledgeSource:
        record = KnowledgeSourceModel(
            id=str(uuid4()),
            filename=filename,
            mime_type=mime_type,
            storage_path=storage_path,
            content_text=content_text,
            status="uploaded",
            error_message=None,
            chunk_count=0,
            created_at=_now(),
            updated_at=_now(),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return _source_to_schema(record)

    def get_source(self, source_id: str) -> KnowledgeSourceModel | None:
        return self.db.get(KnowledgeSourceModel, source_id)

    def get_source_schema(self, source_id: str) -> KnowledgeSource | None:
        source = self.get_source(source_id)
        return _source_to_schema(source) if source else None

    def list_sources(self) -> list[KnowledgeSource]:
        rows = self.db.scalars(
            select(KnowledgeSourceModel).order_by(KnowledgeSourceModel.created_at.desc())
        ).all()
        return [_source_to_schema(item) for item in rows]

    def update_source_text(
        self,
        source_id: str,
        *,
        content_text: str,
        mime_type: str | None = None,
    ) -> KnowledgeSource | None:
        source = self.db.get(KnowledgeSourceModel, source_id)
        if not source:
            return None
        source.content_text = content_text
        if mime_type:
            source.mime_type = mime_type
        source.updated_at = _now()
        self.db.commit()
        self.db.refresh(source)
        return _source_to_schema(source)

    def list_chunks(self, source_id: str | None = None) -> list[KnowledgeChunk]:
        statement = select(KnowledgeChunkModel).order_by(
            KnowledgeChunkModel.created_at.desc(), KnowledgeChunkModel.chunk_index.asc()
        )
        if source_id:
            statement = statement.where(KnowledgeChunkModel.source_id == source_id)
        return [_chunk_to_schema(item) for item in self.db.scalars(statement).all()]

    def replace_chunks(self, source_id: str, chunks: list[dict[str, object]]) -> list[KnowledgeChunk]:
        chunk_ids_subquery = select(KnowledgeChunkModel.id).where(KnowledgeChunkModel.source_id == source_id)
        self.db.query(KnowledgeChunkEmbeddingModel).filter(
            KnowledgeChunkEmbeddingModel.chunk_id.in_(chunk_ids_subquery)
        ).delete(synchronize_session=False)
        self.db.query(KnowledgeChunkModel).filter(KnowledgeChunkModel.source_id == source_id).delete(
            synchronize_session=False
        )
        created: list[KnowledgeChunk] = []
        for chunk in chunks:
            vector = chunk.get("vector") or {}
            record = KnowledgeChunkModel(
                id=str(uuid4()),
                source_id=source_id,
                chunk_index=int(chunk.get("chunk_index", 0)),
                title=chunk.get("title") if chunk.get("title") else None,
                content=str(chunk.get("content") or ""),
                vector_json=json.dumps(vector, ensure_ascii=False),
                token_count=int(chunk.get("token_count", 0)),
                created_at=_now(),
            )
            self.db.add(record)
            created.append(_chunk_to_schema(record))
        source = self.db.get(KnowledgeSourceModel, source_id)
        if source:
            source.status = "parsed"
            source.chunk_count = len(created)
            source.updated_at = _now()
            source.error_message = None
        self.db.commit()
        return created

    def replace_chunk_embeddings(
        self,
        embeddings: list[tuple[str, list[float]]],
        *,
        embedding_model: str,
    ) -> None:
        if not embeddings:
            return
        chunk_ids = [chunk_id for chunk_id, _ in embeddings]
        self.db.query(KnowledgeChunkEmbeddingModel).filter(
            KnowledgeChunkEmbeddingModel.chunk_id.in_(chunk_ids)
        ).delete(synchronize_session=False)
        for chunk_id, vector in embeddings:
            self.db.add(
                KnowledgeChunkEmbeddingModel(
                    chunk_id=chunk_id,
                    embedding_model=embedding_model,
                    embedding_json=json.dumps(vector, ensure_ascii=False),
                    embedding_dim=len(vector),
                    created_at=_now(),
                )
            )
        self.db.commit()

    def mark_source_failed(self, source_id: str, error_message: str) -> KnowledgeSource | None:
        source = self.db.get(KnowledgeSourceModel, source_id)
        if not source:
            return None
        source.status = "failed"
        source.error_message = error_message
        source.updated_at = _now()
        self.db.commit()
        self.db.refresh(source)
        return _source_to_schema(source)

    def set_source_error_message(self, source_id: str, error_message: str | None) -> KnowledgeSource | None:
        source = self.db.get(KnowledgeSourceModel, source_id)
        if not source:
            return None
        source.error_message = error_message
        source.updated_at = _now()
        self.db.commit()
        self.db.refresh(source)
        return _source_to_schema(source)

    def search_chunks(
        self,
        query: str,
        top_k: int = 5,
        *,
        query_embedding: list[float] | None = None,
        embedding_model: str | None = None,
        lexical_weight: float | None = None,
        embedding_weight: float | None = None,
        knowledge_base_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        query_vector = _vectorize(query)
        if not query_vector and not query_embedding:
            return []

        lexical_weight = settings.knowledge_hybrid_lexical_weight if lexical_weight is None else lexical_weight
        embedding_weight = settings.knowledge_hybrid_embedding_weight if embedding_weight is None else embedding_weight
        if lexical_weight < 0:
            lexical_weight = 0.0
        if embedding_weight < 0:
            embedding_weight = 0.0

        statement = select(KnowledgeChunkModel, KnowledgeChunkEmbeddingModel).outerjoin(
            KnowledgeChunkEmbeddingModel,
            KnowledgeChunkModel.id == KnowledgeChunkEmbeddingModel.chunk_id,
        )
        active_sources = select(KnowledgeBaseSourceModel.source_id).join(
            KnowledgeBaseModel, KnowledgeBaseModel.id == KnowledgeBaseSourceModel.knowledge_base_id
        ).where(KnowledgeBaseModel.status == "active")
        if knowledge_base_id:
            active_sources = active_sources.where(KnowledgeBaseModel.id == knowledge_base_id)
        statement = statement.where(KnowledgeChunkModel.source_id.in_(active_sources))
        rows = self.db.execute(statement).all()
        results: list[KnowledgeChunk] = []
        for record, embedding in rows:
            vector = json.loads(record.vector_json or "{}")
            lexical_score = _cosine_similarity(query_vector, {key: int(value) for key, value in vector.items()})
            embedding_score = 0.0
            if query_embedding and embedding and (embedding_model is None or embedding.embedding_model == embedding_model):
                stored_embedding = json.loads(embedding.embedding_json or "[]")
                stored_embedding = [float(value) for value in stored_embedding]
                embedding_score = _dense_cosine_similarity(query_embedding, stored_embedding)

            if lexical_score <= 0 and embedding_score <= 0:
                continue

            if query_embedding and embedding_score > 0:
                total_weight = lexical_weight + embedding_weight
                if total_weight > 0:
                    score = (
                        (lexical_weight / total_weight) * lexical_score
                        + (embedding_weight / total_weight) * embedding_score
                    )
                else:
                    score = lexical_score
            else:
                score = lexical_score

            results.append(_chunk_to_schema(record, score=score))
        results.sort(key=lambda item: item.score or 0, reverse=True)
        return results[:top_k]
