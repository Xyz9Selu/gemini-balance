"""
解析請求體中的本地文件引用：將 files/local/{id} 對應的文件上傳到 Gemini，並替換請求體中的引用為 Gemini 的 file name。
"""
import json
import re
from typing import List, Optional, Tuple

import httpx

from app.config.config import settings
from app.log.logger import get_files_logger
from app.service.files.local_file_service import get_local_file

logger = get_files_logger()

LOCAL_FILE_PREFIX = "files/local/"
BASE_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"


def _extract_file_refs_from_body(body: bytes) -> List[str]:
    """從請求體中提取所有 fileData.fileUri 引用（含 files/ 和 files/local/）。"""
    refs = []
    try:
        payload = json.loads(body)
        for content in payload.get("contents", []):
            for part in content.get("parts", []) or []:
                fd = part.get("fileData") or {}
                uri = fd.get("fileUri") or ""
                if not uri:
                    continue
                if uri.startswith("files/"):
                    refs.append(uri)
                else:
                    match = re.match(rf".*/(files/.*)$", uri)
                    if match:
                        refs.append(match.group(1))
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return refs


def _is_local_file_ref(name: str) -> bool:
    return name.startswith(LOCAL_FILE_PREFIX)


async def _upload_bytes_to_gemini(
    file_bytes: bytes,
    mime_type: str,
    api_key: str,
    display_name: Optional[str] = None,
) -> str:
    """
    將字節數組上傳到 Gemini Files API，返回 file name (files/{id})。
    """
    # Use HTTP/1.1 so X-Goog-Upload-* headers keep casing (Gemini may require it).
    async with httpx.AsyncClient(timeout=300.0, http2=False) as client:
        init_headers = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(file_bytes)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        }
        init_body = json.dumps({"file": {"displayName": display_name or "upload"}})
        init_resp = await client.post(
            BASE_URL,
            headers=init_headers,
            content=init_body.encode("utf-8"),
            params={"key": api_key},
        )
        if init_resp.status_code != 200:
            logger.error(f"Gemini upload init failed: {init_resp.status_code} - {init_resp.text}")
            raise RuntimeError(f"Gemini upload init failed: {init_resp.status_code}")
        upload_url = init_resp.headers.get("x-goog-upload-url")
        if not upload_url:
            raise RuntimeError("No X-Goog-Upload-URL in init response")
        # Resumable upload chunk: PUT with X-Goog-Upload-Offset (required by Gemini).
        upload_headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(file_bytes)),
            "X-Goog-Upload-Command": "upload, finalize",
            "X-Goog-Upload-Offset": "0",
        }
        upload_resp = await client.request(
            "PUT",
            upload_url,
            headers=upload_headers,
            content=file_bytes,
        )
        if upload_resp.status_code not in (200, 201):
            logger.error(f"Gemini upload finalize failed: {upload_resp.status_code} - {upload_resp.text}")
            raise RuntimeError(f"Gemini upload finalize failed: {upload_resp.status_code}")
        data = upload_resp.json()
        file_name = (data.get("file") or {}).get("name")
        if not file_name or not file_name.startswith("files/"):
            raise RuntimeError(f"Invalid Gemini file response: {data}")
        return file_name


def _replace_file_refs_in_json(body_bytes: bytes, mapping: dict) -> bytes:
    """
    在 JSON 請求體中將 mapping 的 key（本地 file name 或完整 URI）替換為 value（完整 File API URI）。
    """
    payload = json.loads(body_bytes)
    base_url_prefix = settings.BASE_URL.rstrip("/") + "/"
    for content in payload.get("contents", []) or []:
        for part in (content.get("parts") or []):
            fd = part.get("fileData")
            if not fd or "fileUri" not in fd:
                continue
            uri = fd["fileUri"]
            if uri in mapping:
                fd["fileUri"] = mapping[uri]
                continue
            if uri.startswith(base_url_prefix):
                rest = uri[len(base_url_prefix) :]
                if rest in mapping:
                    fd["fileUri"] = mapping[rest]
    return json.dumps(payload).encode("utf-8")


async def resolve_local_files_in_body(
    body: bytes,
    api_key: str,
) -> Tuple[bytes, str]:
    """
    解析 body 中所有 files/local/ 引用：從本地讀取文件，上傳到 Gemini，替換 body 中的引用為 Gemini file name。
    Returns:
        (modified_body_bytes, api_key)
    """
    refs = _extract_file_refs_from_body(body)
    local_refs = [r for r in refs if _is_local_file_ref(r)]
    if not local_refs:
        return body, api_key

    # Gemini expects fileUri to be a full File API URL, not the short "files/{id}" form.
    file_api_base = settings.BASE_URL.rstrip("/")
    mapping = {}
    for name in local_refs:
        if name in mapping:
            continue
        result = await get_local_file(name)
        if not result:
            logger.warning(f"Local file not found or expired: {name}")
            raise ValueError(f"Local file not found or expired: {name}")
        file_bytes, mime_type = result
        gemini_name = await _upload_bytes_to_gemini(
            file_bytes,
            mime_type,
            api_key,
            display_name=None,
        )
        full_file_uri = f"{file_api_base}/{gemini_name}"
        mapping[name] = full_file_uri
        if settings.BASE_URL:
            full_uri = f"{settings.BASE_URL.rstrip('/')}/{name}"
            mapping[full_uri] = full_file_uri
    new_body = _replace_file_refs_in_json(body, mapping)
    return new_body, api_key
