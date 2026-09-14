from fastapi import APIRouter

from app.api.routes import ai, knowledge, usage

api_router = APIRouter()
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(usage.router, prefix="/usage", tags=["token-usage"])
