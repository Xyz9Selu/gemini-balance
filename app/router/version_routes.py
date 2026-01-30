from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.utils.helpers import get_current_version
from app.log.logger import get_application_logger

router = APIRouter(prefix="/api/version", tags=["Version"])
logger = get_application_logger()


class VersionInfo(BaseModel):
    current_version: str = Field(..., description="当前应用程序版本")


@router.get("/check", response_model=VersionInfo, summary="获取当前版本")
async def get_version_info():
    """
    返回当前应用程序版本。
    """
    current_version = get_current_version()
    return VersionInfo(current_version=current_version)
