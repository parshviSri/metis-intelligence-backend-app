"""
main.py
──────────────────────────────────────────────────────────────────────────────
FastAPI application factory for Metis Intelligence Backend.

Start-up sequence
─────────────────
1. setup_logging()          — configure structured logging
2. lifespan context         — create DB tables on start, log shutdown
3. CORSMiddleware           — honour CORS_ORIGINS from settings
4. Request logging middleware — INFO log every request/response cycle
5. /health                  — readiness probe (no DB dependency)
6. diagnostic router        — all /api/v1/diagnostic* endpoints
──────────────────────────────────────────────────────────────────────────────
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes.diagnostic import router as diagnostic_router
from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)
settings = get_settings()


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables that don't already exist.
    # In production prefer running Alembic migrations instead.
    Base.metadata.create_all(bind=engine)
    logger.info(
        "Application startup complete — %s v%s",
        settings.app_name,
        settings.app_version,
    )
    yield
    logger.info("Application shutdown complete.")


# ─── Application factory ──────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Production-ready backend for the Metis Intelligence SaaS diagnostic platform. "
        "Accepts business KPI data, calls an LLM, and returns a structured health report."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Request / response logging middleware ────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(
        "→ %s %s",
        request.method,
        request.url.path,
        extra={"method": request.method, "path": request.url.path},
    )
    try:
        response = await call_next(request)
        logger.info(
            "← %s %s [%d]",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )
        return response
    except Exception:
        logger.exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected server error occurred."},
        )


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"], summary="Readiness / liveness probe")
async def health_check() -> dict[str, str]:
    """Returns {status: ok} when the server is running."""
    return {"status": "ok", "version": settings.app_version}


app.include_router(diagnostic_router, prefix=settings.api_v1_prefix)
