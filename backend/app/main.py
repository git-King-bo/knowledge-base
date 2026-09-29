from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db.init_db import init_db, seed_db
from app.db.session import SessionLocal


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.app_env == "production" and not settings.auth_enabled:
            raise RuntimeError("Production requires authentication")
        init_db()
        with SessionLocal() as db:
            seed_db(db)
            from app.core.security import initialize_security
            initialize_security(db)
        from app.services.import_jobs import Worker
        worker = Worker()
        app.state.import_worker = worker
        if settings.worker_enabled:
            worker.start()
        yield
        worker.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    from app.core.observability import observe
    app.middleware("http")(observe)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.routes.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(api_router, prefix="/api")

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    @app.get("/ready")
    def readiness():
        from sqlalchemy import text
        from fastapi import HTTPException
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
            from pathlib import Path
            worker = getattr(app.state, "import_worker", None)
            if settings.worker_enabled and worker and worker.thread and not worker.thread.is_alive():
                raise RuntimeError("Import worker unavailable")
            if not Path(settings.upload_dir).is_dir():
                raise RuntimeError("Upload directory unavailable")
        except Exception:
            raise HTTPException(503, "服务尚未就绪")
        return {"status": "ready"}

    return app


app = create_app()
