from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.ai.registry import ai_provider_registry
from app.db.session import get_db
from app.repositories.sqlite import AIRepository
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    ProviderTestResult,
    ProviderConfig,
    ProviderCreate,
    ProviderModel,
    ProviderModelCreate,
    ProviderUpdate,
)
from app.schemas.knowledge import AIActivityLog

router = APIRouter()


@router.get("/provider-types", response_model=list[str])
def list_provider_types() -> list[str]:
    return ai_provider_registry.available_provider_types()


@router.get("/providers", response_model=list[ProviderConfig])
def list_providers(db: Session = Depends(get_db)) -> list[ProviderConfig]:
    return AIRepository(db).list_providers()


@router.post("/providers", response_model=ProviderConfig, status_code=status.HTTP_201_CREATED)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)) -> ProviderConfig:
    return AIRepository(db).create_provider(payload)


@router.put("/providers/{provider_id}", response_model=ProviderConfig)
def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    db: Session = Depends(get_db),
) -> ProviderConfig:
    provider = AIRepository(db).update_provider(provider_id, payload)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return provider


@router.post("/providers/{provider_id}/switch", response_model=ProviderConfig)
def switch_provider(provider_id: str, db: Session = Depends(get_db)) -> ProviderConfig:
    provider = AIRepository(db).switch_default_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return provider


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResult)
def test_provider(provider_id: str, db: Session = Depends(get_db)) -> ProviderTestResult:
    ai_repository = AIRepository(db)
    provider_record = ai_repository.get_provider_credentials(provider_id)
    if not provider_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    provider, api_key = provider_record
    adapter = ai_provider_registry.resolve(provider.provider)
    started_at = perf_counter()
    result = adapter.test(provider, api_key)
    ai_repository.create_activity_log(
        action="test",
        provider_id=provider.id,
        model=provider.default_model,
        request_text=f"Test provider {provider.name}",
        response_text=result.message,
        success=result.ok,
        latency_ms=int((perf_counter() - started_at) * 1000),
    )
    return result


@router.get("/models", response_model=list[ProviderModel])
def list_models(
    provider_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ProviderModel]:
    return AIRepository(db).list_models(provider_id=provider_id)


@router.post(
    "/providers/{provider_id}/models",
    response_model=ProviderModel,
    status_code=status.HTTP_201_CREATED,
)
def create_model(
    provider_id: str,
    payload: ProviderModelCreate,
    db: Session = Depends(get_db),
) -> ProviderModel:
    model = AIRepository(db).create_model(provider_id, payload)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return model


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    ai_repository = AIRepository(db)
    provider_record = (
        ai_repository.get_provider_credentials(payload.provider_id)
        if payload.provider_id
        else ai_repository.get_default_provider_credentials()
    )
    if not provider_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    provider, api_key = provider_record
    adapter = ai_provider_registry.resolve(provider.provider)
    selected_model = payload.model or provider.default_model
    request_text = "\n".join(f"{message.role}: {message.content}" for message in payload.messages)
    started_at = perf_counter()
    try:
        content = adapter.chat(provider, payload.messages, payload.model, api_key)
        ai_repository.create_activity_log(
            action="chat",
            provider_id=provider.id,
            model=selected_model,
            request_text=request_text,
            response_text=content,
            success=True,
            latency_ms=int((perf_counter() - started_at) * 1000),
        )
    except Exception as exc:
        ai_repository.create_activity_log(
            action="chat",
            provider_id=provider.id,
            model=selected_model,
            request_text=request_text,
            response_text=str(exc),
            success=False,
            latency_ms=int((perf_counter() - started_at) * 1000),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ChatResponse(
        provider_id=provider.id,
        model=selected_model,
        content=content,
    )


@router.get("/logs", response_model=list[AIActivityLog])
def list_ai_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AIActivityLog]:
    return AIRepository(db).list_activity_logs(limit=limit)
