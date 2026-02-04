"""
Service for request log operations.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import delete

from app.config.config import settings
from app.database import services as db_services
from app.database.connection import database
from app.database.models import RequestLog
from app.log.logger import get_request_log_logger

logger = get_request_log_logger()


async def process_get_request_logs(
    limit: int,
    offset: int,
    key_search: Optional[str],
    model_search: Optional[str],
    is_success_filter: Optional[bool],
    status_code_search: Optional[str],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    sort_by: str,
    sort_order: str,
) -> Dict[str, Any]:
    """
    处理请求日志的检索, 支持分页和过滤。
    """
    try:
        logs_data = await db_services.get_request_logs(
            limit=limit,
            offset=offset,
            key_search=key_search,
            model_search=model_search,
            is_success_filter=is_success_filter,
            status_code_search=status_code_search,
            start_date=start_date,
            end_date=end_date,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total_count = await db_services.get_request_logs_count(
            key_search=key_search,
            model_search=model_search,
            is_success_filter=is_success_filter,
            status_code_search=status_code_search,
            start_date=start_date,
            end_date=end_date,
        )
        return {"logs": logs_data, "total": total_count}
    except Exception as e:
        logger.error(f"Service error in process_get_request_logs: {e}", exc_info=True)
        raise


async def delete_old_request_logs_task():
    """
    定时删除旧的请求日志。
    """
    if not settings.AUTO_DELETE_REQUEST_LOGS_ENABLED:
        logger.info(
            "Auto-delete for request logs is disabled by settings. Skipping task."
        )
        return

    days_to_keep = settings.AUTO_DELETE_REQUEST_LOGS_DAYS
    logger.info(
        f"Starting scheduled task to delete old request logs older than {days_to_keep} days."
    )

    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        query = delete(RequestLog).where(RequestLog.request_time < cutoff_date)

        if not database.is_connected:
            logger.info("Connecting to database for request log deletion.")
            await database.connect()

        result = await database.execute(query)
        logger.info(
            f"Request logs older than {cutoff_date} potentially deleted. Rows affected: {result}"
        )

    except Exception as e:
        logger.error(
            f"An error occurred during the scheduled request log deletion: {str(e)}",
            exc_info=True,
        )
