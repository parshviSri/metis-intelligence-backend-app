from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes.diagnostic import router as diagnostic_router
from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("Application startup complete.")
    yield
    logger.info("Application shutdown complete.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("Incoming request", extra={"method": request.method, "path": request.url.path})
    try:
        response = await call_next(request)
        logger.info(
            "Request completed",
            extra={"method": request.method, "path": request.url.path, "status_code": response.status_code},
        )
        return response
    except Exception:
        logger.exception("Unhandled request error", extra={"method": request.method, "path": request.url.path})
        raise


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(diagnostic_router, prefix=settings.api_v1_prefix)
