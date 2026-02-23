"""
文件上传处理器
处理 Google 的可恢复上传协议（本地存储）
"""
import json
from typing import Optional
from datetime import datetime, timezone, timedelta

from fastapi import Request, Response, HTTPException

from app.config.config import settings
from app.log.logger import get_files_logger
from app.service.files.local_file_service import save_local_file

logger = get_files_logger()


class FileUploadHandler:
    """处理文件分块上传（本地存储）"""
    
    def __init__(self):
        self.chunk_size = 8 * 1024 * 1024  # 8MB
    
    async def handle_local_upload(
        self,
        request: Request,
        upload_id: str,
        session_info: dict,
        files_service,
    ) -> Response:
        """
        处理本地上传：累积分块，最终保存到本地并返回 Gemini 形状的响应。
        """
        try:
            if request.method == "GET":
                return Response(
                    status_code=200,
                    headers={"X-Goog-Upload-Status": "active"},
                )
            body = await request.body()
            upload_cmd = (request.headers.get("x-goog-upload-command") or "").strip().lower()
            is_final = "finalize" in upload_cmd
            session_info.setdefault("chunks", []).append(body)
            if not is_final:
                return Response(
                    status_code=308,
                    headers={"X-Goog-Upload-Status": "active"},
                )
            full_data = b"".join(session_info["chunks"])
            mime_type = session_info.get("mime_type", "application/octet-stream")
            display_name = session_info.get("display_name") or None
            file_name = await save_local_file(
                bytes_data=full_data,
                mime_type=mime_type,
                display_name=display_name,
            )
            await files_service.remove_upload_session(upload_id)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=settings.LOCAL_FILE_EXPIRE_MINUTES)
            synthetic = {
                "file": {
                    "name": file_name,
                    "displayName": display_name or "",
                    "mimeType": mime_type,
                    "sizeBytes": str(len(full_data)),
                    "createTime": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "updateTime": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "expirationTime": expires_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "uri": f"{settings.BASE_URL}/{file_name}",
                    "state": "ACTIVE",
                }
            }
            return Response(
                content=json.dumps(synthetic),
                status_code=200,
                media_type="application/json",
            )
        except Exception as e:
            logger.error(f"Local upload failed: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


# 单例实例
_upload_handler_instance: Optional[FileUploadHandler] = None


def get_upload_handler() -> FileUploadHandler:
    """获取上传处理器单例实例"""
    global _upload_handler_instance
    if _upload_handler_instance is None:
        _upload_handler_instance = FileUploadHandler()
    return _upload_handler_instance