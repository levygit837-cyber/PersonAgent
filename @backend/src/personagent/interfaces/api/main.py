"""Aplicação FastAPI principal do PersonAgent."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from personagent.application.jobs.memory_job import JobType
from personagent.application.workflows.scheduler import get_scheduler
from personagent.application.workflows.store import SqlAlchemyWorkflowStore
from personagent.infrastructure.config.settings import get_settings
from personagent.infrastructure.persistence.database import AsyncSessionLocal, init_db
from personagent.interfaces.api.routes import (
    chat,
    conversations,
    lab,
    memory,
    sessions,
    workflows,
    workspace,
)
from personagent.interfaces.config.di_container import get_container

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gerencia o ciclo de vida da aplicação."""
    settings = get_settings()
    container = get_container()
    workflow_session = None

    logger.info(
        "starting_personagent",
        app_name=settings.app_name,
        version=settings.app_version,
        env=settings.app_env,
    )

    # Inicializa banco de dados
    logger.info("initializing_database")
    await init_db()

    # Inicia llama-server se configurado
    if settings.llama_auto_start:
        pm = container.get_process_manager()
        started = await pm.start()
        if started:
            logger.info("llama_server_auto_started")
        else:
            logger.warning("llama_server_auto_start_failed")

    # LightPanda is optional at startup; browser tools report actionable errors when unavailable.
    await container.get_lightpanda_browser_worker().warmup()

    try:
        # Inicializa workflow scheduler
        workflow_session = AsyncSessionLocal()
        scheduler = get_scheduler()
        scheduler.initialize(
            runner=container.get_workflow_runner(),
            store=SqlAlchemyWorkflowStore(workflow_session),
        )
        await scheduler.load_scheduled_workflows()
        scheduler.start()
        logger.info("workflow_scheduler_started")

        # Inicializa memory job scheduler (se habilitado)
        memory_scheduler = None
        if container.settings.auto_memory_enabled:
            memory_scheduler = container.get_memory_job_scheduler()
            memory_scheduler.initialize()
            memory_scheduler.register_handler(
                JobType.EXTRACT_MEMORIES,
                container.create_extract_memory_worker(),
            )
            memory_scheduler.register_handler(
                JobType.AUTO_DREAM,
                container.create_consolidate_memory_worker(),
            )
            if container.settings.auto_dream_enabled:
                memory_scheduler.schedule_cron(
                    JobType.AUTO_DREAM,
                    cron_expr="0 3 * * *",  # 3 AM daily
                    payload={"all_projects": True},
                )
            memory_scheduler.start()
            logger.info("memory_job_scheduler_started")

        yield
    finally:
        # Shutdown
        logger.info("shutting_down_personagent")
        scheduler.shutdown()
        if memory_scheduler is not None:
            memory_scheduler.shutdown()
        if workflow_session is not None:
            await workflow_session.close()
        if container._process_manager:
            container._process_manager.stop()
        await container.close_llm_backends()
        await container.close_browser_workers()


def create_app() -> FastAPI:
    """Factory para criar a aplicação FastAPI."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Sistema de Agente Pessoal com llama.cpp + TurboQuant",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env == "development" else None,
        redoc_url="/redoc" if settings.app_env == "development" else None,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5175",
            "http://localhost:5176",
            "http://127.0.0.1:5176",
            "http://localhost:4176",
            "http://127.0.0.1:4176",
            # Packaged Electron desktop/file origins
            "null",
            "file://",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rotas
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(sessions.router)
    app.include_router(lab.router)
    app.include_router(workflows.router)
    app.include_router(memory.router)
    app.include_router(workspace.router)

    @app.get("/health")
    async def health_check() -> dict:
        """Endpoint de health check."""
        container = get_container()
        default_provider = "llama" if settings.llama_auto_start else "nvidia"
        llm_health = await container.get_llm_backend(default_provider).health_check()
        return {
            "status": "healthy",
            "app": settings.app_name,
            "version": settings.app_version,
            "llm_provider": default_provider,
            "llm_backend": llm_health,
        }

    @app.get("/")
    async def root() -> dict:
        """Endpoint raiz."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    return app


app = create_app()
