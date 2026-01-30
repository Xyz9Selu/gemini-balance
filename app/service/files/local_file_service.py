"""
本地文件服务：保存、获取、删除本地文件，并在保存时清理过期文件。
"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

from app.config.config import settings
from app.database import services as db_services
from app.log.logger import get_files_logger

logger = get_files_logger()


def _upload_dir() -> Path:
    """返回本地上传目录路径（绝对路径）。"""
    p = Path(settings.LOCAL_UPLOAD_DIR)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _file_path(local_id: str) -> Path:
    """根据本地文件 id 返回磁盘上的文件路径。"""
    return _upload_dir() / local_id


async def cleanup_expired_local_files() -> int:
    """
    清理过期的本地文件：删除 DB 记录并删除磁盘上的文件。
    在 save_local_file 中调用。
    Returns:
        int: 删除的记录数
    """
    try:
        expired = await db_services.delete_expired_local_file_records()
        count = 0
        for record in expired:
            local_id = record.get("id")
            if not local_id:
                continue
            fp = _file_path(local_id)
            if fp.exists():
                try:
                    fp.unlink()
                    count += 1
                except OSError as e:
                    logger.warning(f"Failed to delete expired local file {fp}: {e}")
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired local file records, {count} files removed from disk")
        return len(expired)
    except Exception as e:
        logger.error(f"Error cleaning up expired local files: {e}")
        return 0


async def save_local_file(
    bytes_data: bytes,
    mime_type: str,
    display_name: Optional[str] = None,
) -> str:
    """
    将文件保存到本地，插入元数据，返回 file name (files/local/{uuid})。
    先执行 cleanup_expired_local_files()，再写入。
    """
    upload_dir = _upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)

    await cleanup_expired_local_files()

    local_id = uuid.uuid4().hex
    fp = _file_path(local_id)
    fp.write_bytes(bytes_data)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.LOCAL_FILE_EXPIRE_MINUTES)
    await db_services.create_local_file_record(
        id=local_id,
        mime_type=mime_type,
        size_bytes=len(bytes_data),
        expires_at=expires_at,
        display_name=display_name,
    )
    name = f"files/local/{local_id}"
    logger.info(f"Saved local file: {name}, size={len(bytes_data)}, expires_at={expires_at}")
    return name


async def get_local_file(name: str) -> Optional[Tuple[bytes, str]]:
    """
    根据 name (files/local/{id}) 读取本地文件。
    校验未过期（由 get_local_file_record_by_name 保证）。
    Returns:
        Optional[Tuple[bytes, str]]: (bytes_data, mime_type) 或 None
    """
    record = await db_services.get_local_file_record_by_name(name)
    if not record:
        return None
    local_id = record.get("id")
    mime_type = record.get("mime_type", "application/octet-stream")
    if not local_id:
        return None
    fp = _file_path(local_id)
    if not fp.exists():
        logger.warning(f"Local file not found on disk: {fp}")
        return None
    try:
        data = fp.read_bytes()
        return (data, mime_type)
    except OSError as e:
        logger.error(f"Failed to read local file {fp}: {e}")
        return None


def _name_to_local_id(name: str) -> Optional[str]:
    """从 files/local/{id} 提取 id。"""
    if not name or not name.startswith("files/local/"):
        return None
    return name[len("files/local/") :].strip() or None


async def delete_local_file(name: str) -> bool:
    """
    删除本地文件：从磁盘删除并删除 DB 记录。
    name 格式: files/local/{id}
    """
    local_id = _name_to_local_id(name)
    if not local_id:
        return False
    fp = _file_path(local_id)
    if fp.exists():
        try:
            fp.unlink()
        except OSError as e:
            logger.warning(f"Failed to delete local file {fp}: {e}")
    return await db_services.delete_local_file_record(name)


async def get_local_file_metadata(name: str) -> Optional[dict]:
    """
    获取本地文件的元数据（用于 GET /v1beta/files/local/{id} 返回 Gemini 形状）。
    """
    record = await db_services.get_local_file_record_by_name(name)
    if not record:
        return None
    return record
