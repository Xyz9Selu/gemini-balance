from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config.config import settings, sync_initial_settings
from app.database.connection import connect_to_db, disconnect_from_db
from app.database.initialization import initialize_database
from app.exception.exceptions import setup_exception_handlers
from app.log.logger import get_application_logger, setup_access_logging
from app.middleware.middleware import setup_middlewares
from app.router.routes import setup_routers
from app.scheduler.scheduled_tasks import start_scheduler, stop_scheduler
from app.service.key.key_manager import get_key_manager_instance
from app.utils.helpers import get_current_version

logger = get_application_logger()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = PROJECT_ROOT / "app" / "static"
TEMPLATES_DIR = PROJECT_ROOT / "app" / "templates"

# 初始化模板引擎，并添加全局变量
templates = Jinja2Templates(directory="app/templates")


# --- Helper functions for lifespan ---
async def _setup_database_and_config(app_settings):
    """Initializes database, syncs settings, and initializes KeyManager."""
    initialize_database()
    logger.info("Database initialized successfully")
    await connect_to_db()

    # 记录同步前的状态
    logger.info(
        f"[BEFORE SYNC] app_settings.API_KEYS count: {len(app_settings.API_KEYS)}"
    )
    logger.info(f"[BEFORE SYNC] app_settings object id: {id(app_settings)}")
    logger.info(f"[BEFORE SYNC] global settings object id: {id(settings)}")
    logger.info(f"[BEFORE SYNC] app_settings == settings: {app_settings is settings}")

    await sync_initial_settings()

    # 记录同步后的状态
    logger.info(
        f"[AFTER SYNC] app_settings.API_KEYS count: {len(app_settings.API_KEYS)}"
    )
    logger.info(
        f"[AFTER SYNC] global settings.API_KEYS count: {len(settings.API_KEYS)}"
    )
    logger.info(f"[AFTER SYNC] app_settings object id: {id(app_settings)}")
    logger.info(f"[AFTER SYNC] global settings object id: {id(settings)}")
    logger.info(f"[AFTER SYNC] app_settings == settings: {app_settings is settings}")

    # 使用全局 settings 而不是 app_settings 来初始化 KeyManager
    logger.info(
        f"[KEYMANAGER INIT] Using global settings.API_KEYS with {len(settings.API_KEYS)} keys"
    )
    logger.info(
        f"[KEYMANAGER INIT] Using global settings.VERTEX_API_KEYS with {len(settings.VERTEX_API_KEYS)} keys"
    )

    await get_key_manager_instance(settings.API_KEYS, settings.VERTEX_API_KEYS)
    logger.info("Database, config sync, and KeyManager initialized successfully")


async def _shutdown_database():
    """Disconnects from the database."""
    await disconnect_from_db()


def _start_scheduler():
    """Starts the background scheduler."""
    try:
        start_scheduler()
        logger.info("Scheduler started successfully.")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")


def _stop_scheduler():
    """Stops the background scheduler."""
    stop_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application startup and shutdown events.

    Args:
        app: FastAPI应用实例
    """
    logger.info("Application starting up...")
    try:
        await _setup_database_and_config(settings)
        _start_scheduler()

    except Exception as e:
        logger.critical(
            f"Critical error during application startup: {str(e)}", exc_info=True
        )

    yield

    logger.info("Application shutting down...")
    _stop_scheduler()
    await _shutdown_database()


def create_app() -> FastAPI:
    """
    创建并配置FastAPI应用程序实例

    Returns:
        FastAPI: 配置好的FastAPI应用程序实例
    """

    # 创建FastAPI应用
    current_version = get_current_version()
    app = FastAPI(
        title="Gemini Balance API",
        description="Gemini API代理服务，支持负载均衡和密钥管理",
        version=current_version,
        lifespan=lifespan,
    )

    # 配置静态文件
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # 配置中间件
    setup_middlewares(app)

    # 配置异常处理器
    setup_exception_handlers(app)

    # 配置路由
    setup_routers(app)

    # 配置访问日志API密钥隐藏
    setup_access_logging()

    return app
