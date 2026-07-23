"""FastAPI application entry point for the Personal AI Assistant."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.config import settings
from backend.knowledge.db import async_session_maker, init_db
from backend.knowledge.qdrant_client import KnowledgeQdrantClient
from backend.model_router import ModelRouter
from backend.orchestrator import Orchestrator
from backend.skills_loader import SkillsLoader

# ---------------------------------------------------------------------------
# Application-level singletons
# ---------------------------------------------------------------------------
# These are created once during startup and accessed via getter functions that
# are imported by the API routers through lazy imports (avoiding circular deps).

_model_router: ModelRouter | None = None
_skills_loader: SkillsLoader | None = None
_qdrant_client: KnowledgeQdrantClient | None = None
_orchestrator: Orchestrator | None = None


def get_model_router() -> ModelRouter:
    if _model_router is None:
        raise RuntimeError("ModelRouter not initialised — app startup may have failed.")
    return _model_router


def get_skills_loader() -> SkillsLoader:
    if _skills_loader is None:
        raise RuntimeError("SkillsLoader not initialised — app startup may have failed.")
    return _skills_loader


def get_qdrant_client() -> KnowledgeQdrantClient:
    if _qdrant_client is None:
        raise RuntimeError("KnowledgeQdrantClient not initialised — app startup may have failed.")
    return _qdrant_client


def get_orchestrator() -> Orchestrator:
    if _orchestrator is None:
        raise RuntimeError("Orchestrator not initialised — app startup may have failed.")
    return _orchestrator


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise services on startup and clean up (if needed) on shutdown."""
    global _model_router, _skills_loader, _qdrant_client, _orchestrator  # noqa: PLW0603

    # 1. Database tables
    logger.info("Initialising database tables…")
    try:
        await init_db()
        logger.info("Database tables ready.")
    except Exception as exc:
        logger.exception("DB init failed: {}", exc)
        raise

    # 2. Qdrant collection
    logger.info(
        "Initialising Qdrant collection at {}:{}…",
        settings.QDRANT_HOST,
        settings.QDRANT_PORT,
    )
    _qdrant_client = KnowledgeQdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
    )
    try:
        await _qdrant_client.init_collection()
        logger.info("Qdrant collection ready.")
    except Exception as exc:
        logger.warning("Qdrant init failed (non-fatal): {}", exc)

    # 3. Uploads directory
    uploads_dir = settings.UPLOADS_DIR
    uploads_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Uploads directory: {}", uploads_dir)

    # 4. Skills loader
    logger.info("Loading skills from {}…", settings.SKILLS_DIR)
    _skills_loader = SkillsLoader(settings.SKILLS_DIR)
    _skills_loader.load_all()

    # 5. Model router
    _model_router = ModelRouter()

    # 6. Orchestrator
    _orchestrator = Orchestrator(
        model_router=_model_router,
        skills_loader=_skills_loader,
        qdrant_client=_qdrant_client,
        session_maker=async_session_maker,
    )

    # 7. APScheduler (daily digest + future periodic jobs)
    from backend.tasks.scheduler import start_scheduler, stop_scheduler
    scheduler = await start_scheduler()

    # 8. Telegram bot — runs on this same event loop (see telegram_bot.py
    # module docstring for why it must not run in a separate thread/loop).
    _telegram_bot = None
    if settings.TELEGRAM_BOT_TOKEN:
        from backend.bot.telegram_bot import PersonalAssistantBot
        _telegram_bot = PersonalAssistantBot(
            token=settings.TELEGRAM_BOT_TOKEN,
            orchestrator=_orchestrator,
        )
        await _telegram_bot.start()
        logger.info("Telegram bot polling started.")
    else:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot will not start.")

    logger.info("Personal AI Assistant startup complete.")

    yield  # ← application runs here

    logger.info("Personal AI Assistant shutting down.")
    if _telegram_bot is not None:
        await _telegram_bot.stop()
    await stop_scheduler()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="Personal AI Assistant",
        description=(
            "Local-first, privacy-preserving personal knowledge management system "
            "powered by Ollama LLMs and a vector knowledge base."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ------------------------------------------------------------------
    # CORS — localhost only
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # API routers
    # ------------------------------------------------------------------
    from backend.api.agents import router as agents_router
    from backend.api.ingest import router as ingest_router
    from backend.api.knowledge import router as knowledge_router
    from backend.api.settings import router as settings_router

    app.include_router(ingest_router)
    app.include_router(knowledge_router)
    app.include_router(agents_router)
    app.include_router(settings_router)

    # ------------------------------------------------------------------
    # Static files — dashboard served at /dashboard
    # ------------------------------------------------------------------
    dashboard_dir = settings.BASE_DIR / "frontend" / "dist"
    if dashboard_dir.exists():
        app.mount(
            "/dashboard",
            StaticFiles(directory=str(dashboard_dir), html=True),
            name="dashboard",
        )
        logger.info("Dashboard static files mounted from {}", dashboard_dir)
    else:
        logger.info(
            "Dashboard directory '{}' not found — /dashboard will not be served.",
            dashboard_dir,
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    @app.get("/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok", "version": app.version}

    return app


# ---------------------------------------------------------------------------
# Module-level app instance (used by uvicorn / gunicorn)
# ---------------------------------------------------------------------------

app = create_app()
