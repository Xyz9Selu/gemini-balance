"""
解析請求體中的本地文件引用：將 files/local/{id} 對應的文件上傳到 Gemini，並替換請求體中的引用為 Gemini 的 file name。
"""
import json
import re
import asyncio
from typing import Dict, List, Optional, Tuple

import httpx

from app.config.config import settings
from app.log.logger import get_files_logger
from app.service.files.local_file_service import get_local_file

logger = get_files_logger()

LOCAL_FILE_PREFIX = "files/local/"
BASE_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
FILE_STATE_POLL_INTERVAL_SECONDS = 2.0
FILE_STATE_MAX_WAIT_SECONDS = 300.0


def _extract_file_refs_from_body(body: bytes) -> List[str]:
    """從請求體中提取所有 fileData/file_data 引用（含 files/ 和 files/local/）。"""
    refs = []
    try:
        payload = json.loads(body)
        for content in payload.get("contents", []):
            for part in content.get("parts", []) or []:
                fd = part.get("fileData") or part.get("file_data") or {}
                uri = fd.get("fileUri") or fd.get("file_uri") or ""
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
) -> Dict[str, str]:
    """
    將字節數組上傳到 Gemini Files API，等待處理完成，返回 file metadata。
    """
    # Use HTTP/1.1 so X-Goog-Upload-* headers keep casing (Gemini may require it).
    timeout = max(float(settings.TIME_OUT), 300.0)
    async with httpx.AsyncClient(timeout=timeout, http2=False) as client:
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
        file_data = data.get("file") or {}
        file_name = file_data.get("name")
        if not file_name or not file_name.startswith("files/"):
            raise RuntimeError(f"Invalid Gemini file response: {data}")

        file_data = await _wait_for_gemini_file_active(
            client=client,
            file_name=file_name,
            api_key=api_key,
            initial_file=file_data,
        )
        return {
            "name": file_data["name"],
            "uri": file_data.get("uri") or f"{settings.BASE_URL.rstrip('/')}/{file_data['name']}",
            "mime_type": file_data.get("mimeType") or mime_type,
        }


async def _wait_for_gemini_file_active(
    client: httpx.AsyncClient,
    file_name: str,
    api_key: str,
    initial_file: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Poll Gemini Files API until a file is ACTIVE before analysis."""
    file_data = initial_file or {}
    state = file_data.get("state")
    if state == "ACTIVE":
        return file_data
    if state == "FAILED":
        raise RuntimeError(f"Gemini file processing failed: {file_name}")

    deadline = asyncio.get_running_loop().time() + FILE_STATE_MAX_WAIT_SECONDS
    file_url = f"{settings.BASE_URL.rstrip('/')}/{file_name}"
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(FILE_STATE_POLL_INTERVAL_SECONDS)
        resp = await client.get(file_url, params={"key": api_key})
        if resp.status_code != 200:
            logger.warning(
                f"Gemini file state poll failed for {file_name}: {resp.status_code} - {resp.text}"
            )
            continue
        file_data = resp.json()
        state = file_data.get("state")
        if state == "ACTIVE":
            return file_data
        if state == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {file_name}")

    raise TimeoutError(f"Timed out waiting for Gemini file to become ACTIVE: {file_name}")


def _replace_file_refs_in_json(body_bytes: bytes, mapping: dict) -> bytes:
    """
    在 JSON 請求體中將 mapping 的 key（本地 file name 或完整 URI）替換為 value（完整 File API URI）。
    """
    payload = json.loads(body_bytes)
    base_url_prefix = settings.BASE_URL.rstrip("/") + "/"
    for content in payload.get("contents", []) or []:
        for part in (content.get("parts") or []):
            fd = part.get("fileData") or part.get("file_data")
            if not fd:
                continue
            uri_key = "fileUri" if "fileUri" in fd else "file_uri"
            mime_key = "mimeType" if "fileData" in part else "mime_type"
            uri = fd.get(uri_key)
            if not uri:
                continue
            replacement = mapping.get(uri)
            if not replacement and uri.startswith(base_url_prefix):
                replacement = mapping.get(uri[len(base_url_prefix) :])
            if not replacement:
                continue

            fd[uri_key] = replacement["uri"]
            if replacement.get("mime_type") and not fd.get(mime_key):
                fd[mime_key] = replacement["mime_type"]
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

    mapping = {}
    for name in local_refs:
        if name in mapping:
            continue
        result = await get_local_file(name)
        if not result:
            logger.warning(f"Local file not found or expired: {name}")
            raise ValueError(f"Local file not found or expired: {name}")
        file_bytes, mime_type = result
        gemini_file = await _upload_bytes_to_gemini(
            file_bytes,
            mime_type,
            api_key,
            display_name=None,
        )
        mapping[name] = gemini_file
        if settings.BASE_URL:
            full_uri = f"{settings.BASE_URL.rstrip('/')}/{name}"
            mapping[full_uri] = gemini_file
    new_body = _replace_file_refs_in_json(body, mapping)
    return new_body, api_key
