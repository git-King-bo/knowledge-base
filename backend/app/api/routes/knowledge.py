import asyncio
import json
from contextlib import aclosing

import anyio
from starlette.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.registry import ai_provider_registry
from app.core.config import settings
from app.db.session import get_db
from app.repositories.sqlite import AIRepository, KnowledgeIngestionRepository
from app.schemas.ai import ChatMessage
from app.schemas.usage import TokenUsage
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
from app.services.web_search import WebSearchClient

router = APIRouter()


def _require_active_base(repo: KnowledgeIngestionRepository, base_id: str | None):
    if not base_id:
        return
    base = repo.get_knowledge_base(base_id)
    if not base:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if base.status == "archived":
        raise HTTPException(status_code=409, detail="Knowledge base is archived")


def _create_chunk_embeddings(repo: KnowledgeIngestionRepository, chunks: list[KnowledgeChunk], knowledge_base_id: str | None = None) -> str | None:
    embedding_client = EmbeddingClient(db=repo.db, knowledge_base_id=knowledge_base_id)
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


def _should_run_web_search(payload: AskRequest, ranked: list[KnowledgeChunk]) -> bool:
    if payload.web_search_mode == "knowledge":
        return False
    if payload.web_search_mode == "web":
        return True
    best_score = max((item.score or 0 for item in ranked), default=0)
    return len(ranked) < 2 or best_score < settings.web_search_auto_threshold


async def _ingest_upload(
    *,
    file: UploadFile,
    repo: KnowledgeIngestionRepository,
    knowledge_base_id: str | None = None,
) -> UploadResponse:
    _require_active_base(repo, knowledge_base_id)

    upload_root = Path(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "upload.txt").name
    if Path(filename).suffix.lower() not in {'.txt', '.md', '.markdown', '.csv', '.json', '.docx', '.pdf'}:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    raw = await file.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File must be no larger than 20 MB")
    if not raw:
        raise HTTPException(status_code=400, detail="File is empty")
    storage_name = f"{uuid4()}-{filename}"
    storage_path = upload_root / storage_name
    storage_path.write_bytes(raw)

    source = repo.create_source(
        filename=filename,
        mime_type=file.content_type or "application/octet-stream",
        storage_path=str(storage_path),
        content_text="",
    )
    if knowledge_base_id:
        repo.attach_source_to_base(knowledge_base_id, source.id)
    try:
        parsed = parse_uploaded_file(filename, raw)
        if not parsed.text.strip():
            raise ValueError("No readable text found; scanned PDFs require OCR before import")
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
        _create_chunk_embeddings(repo, created_chunks, knowledge_base_id)
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=failed.error_message if failed else str(exc))


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
def rebuild_source_embeddings(
    source_id: str, knowledge_base_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> KnowledgeSource:
    repo = KnowledgeIngestionRepository(db)
    _require_active_base(repo, knowledge_base_id)
    if knowledge_base_id and not any(source.id == source_id for source in repo.list_base_sources(knowledge_base_id)):
        raise HTTPException(status_code=404, detail="Source does not belong to this knowledge base")
    source = repo.get_source_schema(source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    chunks = repo.list_chunks(source_id=source_id)
    if not chunks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source has no parsed chunks")
    if not EmbeddingClient().enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Embedding config is not enabled")

    error_message = _create_chunk_embeddings(repo, chunks, knowledge_base_id)
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
    _require_active_base(repo, knowledge_base_id)
    query_embedding = None
    embedding_client = EmbeddingClient(db=db, knowledge_base_id=knowledge_base_id)
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


def _prepare_ask(payload: AskRequest, db: Session):
    ingestion_repo = KnowledgeIngestionRepository(db)
    _require_active_base(ingestion_repo, payload.knowledge_base_id)
    ai_repo = AIRepository(db)
    provider_record = (
        ai_repo.get_provider_credentials(payload.provider_id)
        if payload.provider_id
        else ai_repo.get_default_provider_credentials()
    )
    if not provider_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    provider, api_key = provider_record
    if payload.continuation is not None:
        ranked = payload.continuation.sources
        web_sources = payload.continuation.web_sources
    else:
        query_embedding = None
        embedding_client = EmbeddingClient(db=db, knowledge_base_id=payload.knowledge_base_id)
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
        web_sources = []
        if _should_run_web_search(payload, ranked):
            try:
                web_sources = WebSearchClient().search(payload.question)
            except Exception:
                web_sources = []

    if not ranked and not web_sources:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No relevant knowledge found")

    context_lines: list[str] = []
    for item in ranked:
        context_lines.append(
            f"[Chunk {item.chunk_index}] file={item.source_id}\n{item.content}"
        )

    web_context_lines: list[str] = []
    for item in web_sources:
        web_context_lines.append(
            f"[Web {item.index}] title={item.title}\nurl={item.url}\n{item.snippet}"
        )

    prompt = (
        "你是一个知识库助手。请只基于给定知识回答问题，并尽量引用来源片段。"
        "引用知识库资料时使用真实切片编号，例如（Chunk 49），不要使用 Source 编号。"
        "引用外部网页资料时使用网页编号，例如（Web 1）。"
        "如果知识库资料和外部网页资料冲突，请明确指出差异。\n\n"
        f"问题：{payload.question}\n\n"
        f"知识库片段：\n{chr(10).join(context_lines) if context_lines else '无'}\n\n"
        f"外部网页资料：\n{chr(10).join(web_context_lines) if web_context_lines else '无'}"
    )
    messages = [
        ChatMessage(role="system", content="你是一个严谨的知识库助手。"),
        ChatMessage(role="user", content=prompt),
    ]
    if payload.continuation and payload.continuation.answer:
        messages.extend([
            ChatMessage(role="assistant", content=payload.continuation.answer),
            ChatMessage(role="user", content="请从上条回答中断处直接继续，只输出新增内容，不要重复已有内容、不要重新开头。保持原来的来源编号；若停在 Markdown 代码块、链接或句子中间，请接着补全，不要重新打开已有标记。"),
        ])
        prompt += "\n\n已生成回答：\n" + payload.continuation.answer + "\n\n继续生成。"
    return provider, api_key, ranked, web_sources, prompt, messages


@router.post("/ask", response_model=AskResponse)
def ask_knowledge(payload: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    provider, api_key, ranked, web_sources, prompt, messages = _prepare_ask(payload, db)
    ai_repo = AIRepository(db)
    started_at = perf_counter()
    adapter = ai_provider_registry.resolve(provider.provider)
    try:
        result = adapter.chat(
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
            response_text=result.content,
            usage=result.usage,
            knowledge_base_id=payload.knowledge_base_id,
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
            knowledge_base_id=payload.knowledge_base_id,
            success=False,
            latency_ms=int((perf_counter() - started_at) * 1000),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return AskResponse(
        answer=result.content,
        provider_id=provider.id,
        model=payload.model or provider.default_model,
        sources=ranked,
        web_sources=web_sources,
    )


@router.post("/ask/stream")
async def stream_knowledge(payload: AskRequest, request: Request, db: Session = Depends(get_db)):
    # Retrieval runs off the event loop; validation errors retain their HTTP status.
    provider, api_key, ranked, web_sources, prompt, messages = await run_in_threadpool(_prepare_ask, payload, db)
    selected_model = payload.model or provider.default_model
    adapter = ai_provider_registry.resolve(provider.provider)

    def event(name, payload):
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generate():
        started = perf_counter()
        parts = []
        length = len(payload.continuation.answer) if payload.continuation else 0
        usage = TokenUsage()
        success = False
        failure = None
        try:
            yield event("meta", {"provider_id": provider.id, "model": selected_model,
                "sources": [source.model_dump(mode="json") for source in ranked],
                "web_sources": [source.model_dump(mode="json") for source in web_sources]})
            async with aclosing(adapter.stream_chat(provider, messages, selected_model, api_key)) as stream:
                async for chunk in stream:
                    if await request.is_disconnected():
                        raise asyncio.CancelledError()
                    if chunk.usage is not None:
                        usage = chunk.usage
                    if chunk.delta:
                        length += len(chunk.delta)
                        if length > 200_000:
                            raise RuntimeError("Answer exceeds streaming size limit")
                        parts.append(chunk.delta)
                        yield event("delta", {"text": chunk.delta})
            if not parts:
                raise RuntimeError("Provider returned no answer content")
            success = True
        except asyncio.CancelledError:
            # Preserve partial usage if the provider reported it before cancellation.
            raise
        except Exception:
            failure = "回答生成中断，请重试；已接收的内容已保留。"
        finally:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(AIRepository(db).create_activity_log,
                    action="ask", provider_id=provider.id, model=selected_model,
                    request_text=prompt, response_text="".join(parts), usage=usage,
                    knowledge_base_id=payload.knowledge_base_id, success=success,
                    latency_ms=int((perf_counter() - started) * 1000))
        if failure:
            yield event("error", {"message": failure})
        else:
            yield event("done", {"usage": usage.model_dump()})

    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
