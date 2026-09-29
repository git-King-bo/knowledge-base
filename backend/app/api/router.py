from fastapi import APIRouter, Depends
from app.core.security import authorize
from app.core.limits import inference_budget

from app.api.routes import ai, knowledge, usage

api_router = APIRouter(dependencies=[Depends(authorize), Depends(inference_budget)])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(usage.router, prefix="/usage", tags=["token-usage"])

from app.api.routes.workspace import router as workspace_router
api_router.include_router(workspace_router, tags=["workspace"])
