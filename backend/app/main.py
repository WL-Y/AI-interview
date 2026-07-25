"""FastAPI application factory."""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import interview
from app.core.startup import run_startup_checks
from app.services.llm_service import has_real_llm

# Session cleanup interval (seconds)
_CLEANUP_INTERVAL = 300
_last_cleanup = 0.0


async def _session_cleanup_middleware(request: Request, call_next):
    """Periodically clean up expired in-memory sessions."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup > _CLEANUP_INTERVAL:
        _last_cleanup = now
        # Delegate to the API module's cleanup
        interview.cleanup_expired_sessions()
    return await call_next(request)


# ── Lifespan ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    run_startup_checks()
    yield


# ── App ──────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="AI 面试 Agent",
        version="0.3.0",
        lifespan=lifespan,
    )

    # Session cleanup middleware
    app.middleware("http")(_session_cleanup_middleware)

    # CORS — allow Next.js dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(interview.router, prefix="/api/interview", tags=["interview"])

    # ── Global error handler ─────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": str(exc) if app.debug else "服务器内部错误，请稍后重试。",
            },
        )

    # ── Health check ─────────────────────────────────────
    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": "0.3.0",
            "llm": "real" if has_real_llm() else "mock",
        }

    return app


app = create_app()
