import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.init_db import init_db

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) Configure logging first
    configure_logging()
    logger.info("RepoBrain API starting up...")

    # 2) Initialize DB with error handling and timeout
    try:
        logger.info("Attempting database initialization...")
        init_db()
        logger.info("Database initialization completed successfully")
    except Exception as exc:
        logger.warning(f"Database initialization failed on startup: {exc}")
        logger.warning("Service is starting in DEGRADED mode (DB unavailable)")
        # Continue startup - don't block on DB issues

    logger.info("RepoBrain API startup complete - ready to serve requests")
    yield
    logger.info("RepoBrain API shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router)


@app.get("/")
def root():
    return {
        "message": "RepoBrain API is running",
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }