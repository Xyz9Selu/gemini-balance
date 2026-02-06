from fastapi import APIRouter, Depends, HTTPException, Request
from starlette import status
from app.core.security import verify_auth_token
from app.service.stats.stats_service import StatsService
from app.log.logger import get_stats_logger
from app.utils.helpers import redact_key_for_logging

logger = get_stats_logger()


async def verify_token(request: Request):
    auth_token = request.cookies.get("auth_token")
    if not auth_token or not verify_auth_token(auth_token):
        logger.warning("Unauthorized access attempt to scheduler API")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

router = APIRouter(
    prefix="/api",
    tags=["stats"],
    dependencies=[Depends(verify_token)]
)

stats_service = StatsService()

@router.get(
    "/stats/model-call-stats",
    summary="Get model call stats (overall and quota cycle)",
    description="Returns total, success, and failed call counts per model for both overall (all time) and quota_cycle (since last Gemini quota reset) periods.",
)
async def get_model_call_stats():
    """Get model call statistics for overall and quota cycle periods."""
    try:
        data = await stats_service.get_model_call_stats_both_periods()
        return data
    except Exception as e:
        logger.error(f"Error fetching model call stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch model call stats: {e}",
        )


@router.get("/key-usage-details/{key}",
            summary="获取指定密钥最近24小时的模型调用次数",
            description="根据提供的 API 密钥，返回过去24小时内每个模型被调用的次数统计。")
async def get_key_usage_details(key: str):
    """
    Retrieves the model usage count for a specific API key within the last 24 hours.

    Args:
        key: The API key to get usage details for.

    Returns:
        A dictionary with model names as keys and their call counts as values.
        Example: {"gemini-pro": 10, "gemini-1.5-pro-latest": 5}

    Raises:
        HTTPException: If an error occurs during data retrieval.
    """
    try:
        usage_details = await stats_service.get_key_usage_details_last_24h(key)
        if usage_details is None:
            return {}
        return usage_details
    except Exception as e:
        logger.error(f"Error fetching key usage details for key {redact_key_for_logging(key)}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取密钥使用详情时出错: {e}"
        )