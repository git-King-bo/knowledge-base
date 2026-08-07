from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.registry import ai_provider_registry
from app.core.config import settings
from app.db.session import get_db
from app.repositories.sqlite import AIRepository, KnowledgeIngestionRepository
from app.schemas.ai import ChatMessage
from app.schemas.knowledge import (
    AskRequest,
    AskResponse,
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeChunk,
    KnowledgeSearchResult,
    KnowledgeSource,
    UploadResponse,
)
from app.services.embeddings import EmbeddingClient
from app.services.ingestion import parse_uploaded_file, split_into_chunks

router = APIRouter()


def _create_chunk_embeddings(repo: KnowledgeIngestionRepository, chunks: list[KnowledgeChunk]) -> str | None:
    embedding_client = EmbeddingClient()
    if not embedding_client.enabled or not chunks:
        return None
    try:
        embeddings: list[list[float]] = []
        for start in range(0, len(chunks), max(settings.embedding_batch_size, 1)):
            batch = chunks[start : start + max(settings.embedding_batch_size, 1)]
            embeddings.extend(embedding_client.embed_texts([item.content for item in batch]))
        repo.replace_chunk_embeddings(
            [(chunk.id, vector) for chunk, vector in zip(chunks, embeddings, strict=True)],
            embedding_model=settings.embedding_model,
        )
        repo.set_source_error_message(chunks[0].source_id, None)
        return None
    except Exception as exc:
        error_message = f"Embedding generation failed: {exc}"
        repo.set_source_error_message(chunks[0].source_id, error_message)
        return error_message


async def _ingest_upload(
    *,
    file: UploadFile,
    repo: KnowledgeIngestionRepository,
    knowledge_base_id: str | None = None,
) -> UploadResponse:
    if knowledge_base_id and not repo.get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")

    upload_root = Path(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    raw = await file.read()
    storage_name = f"{uuid4()}-{file.filename}"
    storage_path = upload_root / storage_name
    storage_path.write_bytes(raw)

    source = repo.create_source(
        filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        storage_path=str(storage_path),
        content_text="",
    )
    try:
        parsed = parse_uploaded_file(file.filename, raw)
        repo.update_source_text(source.id, content_text=parsed.text, mime_type=parsed.mime_type)
        chunks = split_into_chunks(
            parsed.text,
            max_chars=settings.knowledge_chunk_max_chars,
            overlap=settings.knowledge_chunk_overlap_chars,
        )
        created_chunks = repo.replace_chunks(
            source.id,
            [
                {
                    "chunk_index": chunk.chunk_index,
                    "title": parsed.title if chunk.chunk_index == 0 else None,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "vector": chunk.vector,
                }
                for chunk in chunks
            ],
        )
        _create_chunk_embeddings(repo, created_chunks)
        if knowledge_base_id:
            repo.attach_source_to_base(knowledge_base_id, source.id)
        stored_source = repo.get_source_schema(source.id)
        if not stored_source:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load uploaded source")
        return UploadResponse(
            source=stored_source,
            chunks=created_chunks,
            knowledge_base=repo.get_knowledge_base(knowledge_base_id) if knowledge_base_id else None,
        )
    except Exception as exc:
        failed = repo.mark_source_failed(source.id, str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=failed.model_dump() if failed else str(exc))


@router.get("/bases", response_model=list[KnowledgeBase])
def list_knowledge_bases(db: Session = Depends(get_db)) -> list[KnowledgeBase]:
    return KnowledgeIngestionRepository(db).list_knowledge_bases()


@router.post("/bases", response_model=KnowledgeBase, status_code=status.HTTP_201_CREATED)
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
) -> KnowledgeBase:
    return KnowledgeIngestionRepository(db).create_knowledge_base(payload)


@router.put("/bases/{knowledge_base_id}", response_model=KnowledgeBase)
def update_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
) -> KnowledgeBase:
    next_base = KnowledgeIngestionRepository(db).update_knowledge_base(knowledge_base_id, payload)
    if not next_base:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
    return next_base


@router.delete("/bases/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_base(
    knowledge_base_id: str,
    db: Session = Depends(get_db),
) -> None:
    deleted = KnowledgeIngestionRepository(db).delete_knowledge_base(knowledge_base_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")


@router.get("/bases/{knowledge_base_id}/sources", response_model=list[KnowledgeSource])
def list_knowledge_base_sources(
    knowledge_base_id: str,
    db: Session = Depends(get_db),
) -> list[KnowledgeSource]:
    repo = KnowledgeIngestionRepository(db)
    if not repo.get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
    return repo.list_base_sources(knowledge_base_id)


@router.get("/bases/{knowledge_base_id}/chunks", response_model=list[KnowledgeChunk])
def list_knowledge_base_chunks(
    knowledge_base_id: str,
    db: Session = Depends(get_db),
) -> list[KnowledgeChunk]:
    repo = KnowledgeIngestionRepository(db)
    if not repo.get_knowledge_base(knowledge_base_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
    return repo.list_base_chunks(knowledge_base_id)


@router.delete("/bases/{knowledge_base_id}/sources/{source_id}", response_model=KnowledgeBase)
def remove_knowledge_base_source(
    knowledge_base_id: str,
    source_id: str,
    db: Session = Depends(get_db),
) -> KnowledgeBase:
    repo = KnowledgeIngestionRepository(db)
    next_base = repo.detach_source_from_base(knowledge_base_id, source_id)
    if not next_base:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
    return next_base


@router.post("/bases/{knowledge_base_id}/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_base_file(
    knowledge_base_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    return await _ingest_upload(file=file, repo=KnowledgeIngestionRepository(db), knowledge_base_id=knowledge_base_id)


@router.get("/sources", response_model=list[KnowledgeSource])
def list_sources(db: Session = Depends(get_db)) -> list[KnowledgeSource]:
    repo = KnowledgeIngestionRepository(db)
    return repo.list_sources()


@router.get("/sources/{source_id}/chunks", response_model=list[KnowledgeChunk])
def list_source_chunks(source_id: str, db: Session = Depends(get_db)) -> list[KnowledgeChunk]:
    repo = KnowledgeIngestionRepository(db)
    return repo.list_chunks(source_id=source_id)


@router.post("/sources/{source_id}/embeddings/rebuild", response_model=KnowledgeSource)
def rebuild_source_embeddings(source_id: str, db: Session = Depends(get_db)) -> KnowledgeSource:
    repo = KnowledgeIngestionRepository(db)
    source = repo.get_source_schema(source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    chunks = repo.list_chunks(source_id=source_id)
    if not chunks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source has no parsed chunks")
    if not EmbeddingClient().enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Embedding config is not enabled")

    error_message = _create_chunk_embeddings(repo, chunks)
    next_source = repo.get_source_schema(source_id)
    if not next_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    if error_message:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error_message)
    return next_source


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    repo = KnowledgeIngestionRepository(db)
    return await _ingest_upload(file=file, repo=repo)


@router.get("/search", response_model=KnowledgeSearchResult)
def search_knowledge(
    q: str = Query(min_length=1),
    top_k: int = Query(default=5, ge=1, le=12),
    knowledge_base_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> KnowledgeSearchResult:
    repo = KnowledgeIngestionRepository(db)
    query_embedding = None
    embedding_client = EmbeddingClient()
    if embedding_client.enabled:
        try:
            query_embedding = embedding_client.embed_text(q)
        except Exception:
            query_embedding = None
    ranked = repo.search_chunks(
        q,
        top_k=top_k,
        query_embedding=query_embedding,
        embedding_model=settings.embedding_model if query_embedding else None,
        knowledge_base_id=knowledge_base_id,
    )
    return KnowledgeSearchResult(query=q, hits=ranked)


@router.post("/ask", response_model=AskResponse)
def ask_knowledge(payload: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    ingestion_repo = KnowledgeIngestionRepository(db)
    ai_repo = AIRepository(db)
    provider_record = (
        ai_repo.get_provider_credentials(payload.provider_id)
        if payload.provider_id
        else ai_repo.get_default_provider_credentials()
    )
    if not provider_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    provider, api_key = provider_record
    query_embedding = None
    embedding_client = EmbeddingClient()
    if embedding_client.enabled:
        try:
            query_embedding = embedding_client.embed_text(payload.question)
        except Exception:
            query_embedding = None
    ranked = ingestion_repo.search_chunks(
        payload.question,
        top_k=payload.top_k,
        query_embedding=query_embedding,
        embedding_model=settings.embedding_model if query_embedding else None,
        knowledge_base_id=payload.knowledge_base_id,
    )
    if not ranked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No relevant knowledge found")

    context_lines: list[str] = []
    for item in ranked:
        context_lines.append(
            f"[Chunk {item.chunk_index}] file={item.source_id}\n{item.content}"
        )

    prompt = (
        "你是一个知识库助手。请只基于给定知识回答问题，并尽量引用来源片段。"
        "引用时使用真实切片编号，例如（Chunk 49），不要使用 Source 编号。\n\n"
        f"问题：{payload.question}\n\n"
        f"知识片段：\n{chr(10).join(context_lines)}"
    )
    started_at = perf_counter()
    adapter = ai_provider_registry.resolve(provider.provider)
    try:
        messages = [
            ChatMessage(role="system", content="你是一个严谨的知识库助手。"),
            ChatMessage(role="user", content=prompt),
        ]
        answer = adapter.chat(
            provider,
            messages,
            payload.model or provider.default_model,
            api_key,
        )
        ai_repo.create_activity_log(
            action="ask",
            provider_id=provider.id,
            model=payload.model or provider.default_model,
            request_text=prompt,
            response_text=answer,
            success=True,
            latency_ms=int((perf_counter() - started_at) * 1000),
        )
    except Exception as exc:
        ai_repo.create_activity_log(
            action="ask",
            provider_id=provider.id,
            model=payload.model or provider.default_model,
            request_text=prompt,
            response_text=str(exc),
            success=False,
            latency_ms=int((perf_counter() - started_at) * 1000),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return AskResponse(
        answer=answer,
        provider_id=provider.id,
        model=payload.model or provider.default_model,
        sources=ranked,
    )
