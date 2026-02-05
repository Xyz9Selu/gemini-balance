# app/service/stats_service.py

import datetime
from typing import Union

import zoneinfo
from sqlalchemy import and_, case, func, or_, select

from app.config.config import settings
from app.database.connection import database
from app.database.models import ErrorLog, RequestLog
from app.log.logger import get_stats_logger

logger = get_stats_logger()


def get_quota_cycle_start_time() -> datetime.datetime:
    """
    Get the start datetime of the current quota cycle based on configured
    QUOTA_RESET_HOUR and TIMEZONE (e.g. Gemini resets at 16:00 UTC+8).
    """
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    now = datetime.datetime.now(tz)
    reset_hour = getattr(settings, "QUOTA_RESET_HOUR", 16)
    today_reset = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if now >= today_reset:
        return today_reset
    yesterday_reset = today_reset - datetime.timedelta(days=1)
    return yesterday_reset


class StatsService:
    """Service class for handling statistics related operations."""

    async def get_calls_in_last_seconds(self, seconds: int) -> dict[str, int]:
        """获取过去 N 秒内的调用次数 (总数、成功、失败)"""
        try:
            cutoff_time = datetime.datetime.now() - datetime.timedelta(seconds=seconds)
            query = select(
                func.count(RequestLog.id).label("total"),
                func.sum(
                    case(
                        (
                            and_(
                                RequestLog.status_code >= 200,
                                RequestLog.status_code < 300,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("success"),
                func.sum(
                    case(
                        (
                            or_(
                                RequestLog.status_code < 200,
                                RequestLog.status_code >= 300,
                            ),
                            1,
                        ),
                        (RequestLog.status_code is None, 1),
                        else_=0,
                    )
                ).label("failure"),
            ).where(RequestLog.request_time >= cutoff_time)
            result = await database.fetch_one(query)
            if result:
                return {
                    "total": result["total"] or 0,
                    "success": result["success"] or 0,
                    "failure": result["failure"] or 0,
                }
            return {"total": 0, "success": 0, "failure": 0}
        except Exception as e:
            logger.error(f"Failed to get calls in last {seconds} seconds: {e}")
            return {"total": 0, "success": 0, "failure": 0}

    async def get_calls_in_last_minutes(self, minutes: int) -> dict[str, int]:
        """获取过去 N 分钟内的调用次数 (总数、成功、失败)"""
        return await self.get_calls_in_last_seconds(minutes * 60)

    async def get_calls_in_last_hours(self, hours: int) -> dict[str, int]:
        """获取过去 N 小时内的调用次数 (总数、成功、失败)"""
        return await self.get_calls_in_last_seconds(hours * 3600)

    async def get_calls_in_current_month(self) -> dict[str, int]:
        """获取当前自然月内的调用次数 (总数、成功、失败)"""
        try:
            now = datetime.datetime.now()
            start_of_month = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            query = select(
                func.count(RequestLog.id).label("total"),
                func.sum(
                    case(
                        (
                            and_(
                                RequestLog.status_code >= 200,
                                RequestLog.status_code < 300,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("success"),
                func.sum(
                    case(
                        (
                            or_(
                                RequestLog.status_code < 200,
                                RequestLog.status_code >= 300,
                            ),
                            1,
                        ),
                        (RequestLog.status_code is None, 1),
                        else_=0,
                    )
                ).label("failure"),
            ).where(RequestLog.request_time >= start_of_month)
            result = await database.fetch_one(query)
            if result:
                return {
                    "total": result["total"] or 0,
                    "success": result["success"] or 0,
                    "failure": result["failure"] or 0,
                }
            return {"total": 0, "success": 0, "failure": 0}
        except Exception as e:
            logger.error(f"Failed to get calls in current month: {e}")
            return {"total": 0, "success": 0, "failure": 0}

    async def get_api_usage_stats(self) -> dict:
        """获取所有需要的 API 使用统计数据 (总数、成功、失败)"""
        try:
            stats_1m = await self.get_calls_in_last_minutes(1)
            stats_1h = await self.get_calls_in_last_hours(1)
            stats_24h = await self.get_calls_in_last_hours(24)
            stats_month = await self.get_calls_in_current_month()

            return {
                "calls_1m": stats_1m,
                "calls_1h": stats_1h,
                "calls_24h": stats_24h,
                "calls_month": stats_month,
            }
        except Exception as e:
            logger.error(f"Failed to get API usage stats: {e}")
            default_stat = {"total": 0, "success": 0, "failure": 0}
            return {
                "calls_1m": default_stat.copy(),
                "calls_1h": default_stat.copy(),
                "calls_24h": default_stat.copy(),
                "calls_month": default_stat.copy(),
            }

    async def get_api_call_details(self, period: str) -> list[dict]:
        """
        获取指定时间段内的 API 调用详情

        合并 RequestLog 与 ErrorLog，确保失败记录（如 gemini-proxy 503/403）在趋势图中正确显示。
        ErrorLog 中的每条记录代表一次失败，与 RequestLog 的失败记录一起计入失败数。

        Args:
            period: 时间段标识 ('1m', '1h', '8h', '24h')

        Returns:
            包含调用详情的字典列表，每个字典包含 timestamp, key, model, status, status_code, latency_ms

        Raises:
            ValueError: 如果 period 无效
        """
        now = datetime.datetime.now()
        if period == "1m":
            start_time = now - datetime.timedelta(minutes=1)
        elif period == "1h":
            start_time = now - datetime.timedelta(hours=1)
        elif period == "8h":
            start_time = now - datetime.timedelta(hours=8)
        elif period == "24h":
            start_time = now - datetime.timedelta(hours=24)
        else:
            raise ValueError(f"无效的时间段标识: {period}")

        try:
            # 1. 从 RequestLog 获取所有调用记录
            request_query = (
                select(
                    RequestLog.request_time.label("timestamp"),
                    RequestLog.api_key.label("key"),
                    RequestLog.model_name.label("model"),
                    RequestLog.status_code.label("status_code"),
                    RequestLog.latency_ms.label("latency_ms"),
                )
                .where(RequestLog.request_time >= start_time)
                .order_by(RequestLog.request_time.desc())
            )
            request_results = await database.fetch_all(request_query)

            # 2. 从 ErrorLog 获取失败记录（与 RequestLog 合并，确保趋势图显示所有失败）
            error_query = (
                select(
                    ErrorLog.request_time.label("timestamp"),
                    ErrorLog.gemini_key.label("key"),
                    ErrorLog.model_name.label("model"),
                    ErrorLog.error_code.label("status_code"),
                )
                .where(ErrorLog.request_time >= start_time)
                .order_by(ErrorLog.request_time.desc())
            )
            error_results = await database.fetch_all(error_query)

            details: list[dict] = []
            for row in request_results:
                status = "failure"
                if row["status_code"] is not None:
                    status = "success" if 200 <= row["status_code"] < 300 else "failure"
                details.append({
                    "timestamp": row["timestamp"].isoformat(),
                    "key": row["key"],
                    "model": row["model"],
                    "status": status,
                    "status_code": row["status_code"],
                    "latency_ms": row["latency_ms"],
                })

            for row in error_results:
                details.append({
                    "timestamp": row["timestamp"].isoformat(),
                    "key": row["key"],
                    "model": row["model"],
                    "status": "failure",
                    "status_code": row["status_code"],
                    "latency_ms": None,
                })

            # 按时间倒序排列（与前端 bucketize 逻辑兼容）
            details.sort(key=lambda r: r["timestamp"], reverse=True)

            logger.info(
                f"Retrieved {len(details)} API call details for period '{period}' "
                f"(RequestLog: {len(request_results)}, ErrorLog: {len(error_results)})"
            )
            return details

        except Exception as e:
            logger.error(f"Failed to get API call details for period '{period}': {e}")
            raise

    async def get_key_call_details(self, key: str, period: str) -> list[dict]:
        """获取指定密钥在指定时间段内的调用详情 (与 get_api_call_details 结构一致)"""
        now = datetime.datetime.now()
        if period == "1m":
            start_time = now - datetime.timedelta(minutes=1)
        elif period == "1h":
            start_time = now - datetime.timedelta(hours=1)
        elif period == "8h":
            start_time = now - datetime.timedelta(hours=8)
        elif period == "24h":
            start_time = now - datetime.timedelta(hours=24)
        else:
            raise ValueError(f"无效的时间段标识: {period}")

        try:
            query = (
                select(
                    RequestLog.request_time.label("timestamp"),
                    RequestLog.api_key.label("key"),
                    RequestLog.model_name.label("model"),
                    RequestLog.status_code.label("status_code"),
                    RequestLog.latency_ms.label("latency_ms"),
                )
                .where(RequestLog.request_time >= start_time, RequestLog.api_key == key)
                .order_by(RequestLog.request_time.desc())
            )

            results = await database.fetch_all(query)

            details: list[dict] = []
            for row in results:
                status = "failure"
                if row["status_code"] is not None:
                    status = "success" if 200 <= row["status_code"] < 300 else "failure"

                record = {
                    "timestamp": row["timestamp"].isoformat(),
                    "key": row["key"],
                    "model": row["model"],
                    "status": status,
                    "status_code": row["status_code"],
                    "latency_ms": row["latency_ms"],
                }

                details.append(record)

            logger.info(
                f"Retrieved {len(details)} key call details for key=...{key[-4:] if key else ''} period '{period}'"
            )
            return details
        except Exception as e:
            logger.error(
                f"Failed to get key call details for key=...{key[-4:] if key else ''} period '{period}': {e}"
            )
            raise

    async def get_attention_keys_last_24h(
        self, include_keys: set[str], limit: int = 20, status_code: int = 429
    ) -> list[dict]:
        """返回最近24小时内指定状态码(默认429)最多的Key列表，仅包含include_keys中的Key。

        Returns: [{"key": str, "count": int, "status_code": int}, ...] 按次数降序
        """
        try:
            now = datetime.datetime.now()
            start_time = now - datetime.timedelta(hours=24)
            if not include_keys:
                return []
            query = (
                select(
                    RequestLog.api_key.label("key"),
                    func.count(RequestLog.id).label("count"),
                )
                .where(
                    RequestLog.request_time >= start_time,
                    RequestLog.status_code == status_code,
                    RequestLog.api_key.isnot(None),
                    RequestLog.api_key.in_(list(include_keys)),
                )
                .group_by(RequestLog.api_key)
                .order_by(func.count(RequestLog.id).desc())
                .limit(limit)
            )
            rows = await database.fetch_all(query)
            return [
                {"key": row["key"], "count": row["count"], "status_code": status_code}
                for row in rows
                if row["key"]
            ]
        except Exception as e:
            logger.error(
                f"Failed to get attention keys ({status_code}) in last 24h: {e}"
            )
            return []

    async def get_keys_call_stats(
        self, keys: list[str], period: str = "quota_cycle"
    ) -> dict[str, dict[str, int]]:
        """
        Get call_count, success_count and failed_count per key for the given period (from RequestLog).

        Args:
            keys: List of API keys to get stats for.
            period: Time period ('1h', '8h', '24h', 'quota_cycle', 'overall').
                   - quota_cycle: since last Gemini quota reset (e.g. 16:00 UTC+8)
                   - overall: all time

        Returns:
            {key: {"call_count": int, "success_count": int, "failed_count": int}}
        """
        if not keys:
            return {}
        now = datetime.datetime.now()
        if period == "overall":
            start_time = None  # No lower bound
        elif period == "quota_cycle":
            cycle_start = get_quota_cycle_start_time()
            # Convert to naive local datetime for DB comparison (RequestLog uses naive)
            start_time = datetime.datetime.fromtimestamp(cycle_start.timestamp())
        elif period == "1h":
            start_time = now - datetime.timedelta(hours=1)
        elif period == "8h":
            start_time = now - datetime.timedelta(hours=8)
        elif period == "24h":
            start_time = now - datetime.timedelta(hours=24)
        else:
            cycle_start = get_quota_cycle_start_time()
            start_time = datetime.datetime.fromtimestamp(cycle_start.timestamp())

        try:
            conditions = [
                RequestLog.api_key.isnot(None),
                RequestLog.api_key.in_(keys),
            ]
            if start_time is not None:
                conditions.append(RequestLog.request_time >= start_time)

            query = (
                select(
                    RequestLog.api_key.label("key"),
                    func.count(RequestLog.id).label("call_count"),
                    func.sum(
                        case(
                            (
                                and_(
                                    RequestLog.status_code >= 200,
                                    RequestLog.status_code < 300,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("success_count"),
                    func.sum(
                        case(
                            (
                                or_(
                                    RequestLog.status_code < 200,
                                    RequestLog.status_code >= 300,
                                ),
                                1,
                            ),
                            (RequestLog.status_code.is_(None), 1),
                            else_=0,
                        )
                    ).label("failed_count"),
                )
                .where(and_(*conditions))
                .group_by(RequestLog.api_key)
            )
            rows = await database.fetch_all(query)
            result = {}
            for row in rows:
                if row["key"]:
                    call_count = row["call_count"] or 0
                    success_count = int(row["success_count"] or 0)
                    failed_count = int(row["failed_count"] or 0)
                    result[row["key"]] = {
                        "call_count": call_count,
                        "success_count": success_count,
                        "failed_count": failed_count,
                    }
            # Ensure all keys have an entry (default 0 for keys with no logs)
            for key in keys:
                if key not in result:
                    result[key] = {"call_count": 0, "success_count": 0, "failed_count": 0}
            return result
        except Exception as e:
            logger.error(f"Failed to get keys call stats: {e}")
            return {
                k: {"call_count": 0, "success_count": 0, "failed_count": 0}
                for k in keys
            }

    async def get_key_usage_details_last_24h(self, key: str) -> Union[dict, None]:
        """
        获取指定 API 密钥在过去 24 小时内按模型统计的调用次数。

        Args:
            key: 要查询的 API 密钥。

        Returns:
            一个字典，其中键是模型名称，值是调用次数。
            如果查询出错或没有找到记录，可能返回 None 或空字典。
            Example: {"gemini-pro": 10, "gemini-1.5-pro-latest": 5}
        """
        logger.info(
            f"Fetching usage details for key ending in ...{key[-4:]} for the last 24h."
        )
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=24)

        try:
            query = (
                select(
                    RequestLog.model_name, func.count(RequestLog.id).label("call_count")
                )
                .where(
                    RequestLog.api_key == key,
                    RequestLog.request_time >= cutoff_time,
                    RequestLog.model_name.isnot(None),
                )
                .group_by(RequestLog.model_name)
                .order_by(func.count(RequestLog.id).desc())
            )

            results = await database.fetch_all(query)

            if not results:
                logger.info(
                    f"No usage details found for key ending in ...{key[-4:]} in the last 24h."
                )
                return {}

            usage_details = {row["model_name"]: row["call_count"] for row in results}
            logger.info(
                f"Successfully fetched usage details for key ending in ...{key[-4:]}: {usage_details}"
            )
            return usage_details

        except Exception as e:
            logger.error(
                f"Failed to get key usage details for key ending in ...{key[-4:]}: {e}",
                exc_info=True,
            )
            raise
