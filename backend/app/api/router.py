from fastapi import APIRouter

from app.api.routes import ai, categories, documents, knowledge

api_router = APIRouter()
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
