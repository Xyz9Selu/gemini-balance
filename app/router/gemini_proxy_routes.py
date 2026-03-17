"""
Gemini transparent transmission (raw reverse-proxy) routes.

This router forwards any /v1beta/** (and /gemini/v1beta/**) request to the upstream
Gemini Generative Language API, injecting a server-managed API key and performing
key switching retries on transient failures.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import re
import time
from typing import AsyncGenerator, Dict, Iterable, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from app.config.config import settings
from app.core.security import SecurityService
from app.database.services import add_error_log, add_request_log, get_file_api_key
from app.log.logger import get_gemini_logger
from app.service.files.local_file_resolver import resolve_local_files_in_body
from app.service.key.key_manager import KeyManager, get_key_manager_instance
from app.service.rate_limit.model_rpm_limiter import model_rpm_limiter
from app.utils.helpers import extract_total_token_count_from_gemini_response, redact_key_for_logging

logger = get_gemini_logger()
security_service = SecurityService()

router = APIRouter()


async def _get_key_manager() -> KeyManager:
    # Be defensive: if lifespan init was skipped/failed, initialize lazily.
    return await get_key_manager_instance(settings.API_KEYS, settings.VERTEX_API_KEYS)


_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _filter_outgoing_headers(headers: Iterable[Tuple[bytes, bytes]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k_b, v_b in headers:
        k = k_b.decode("latin-1").lower()
        if k in _HOP_BY_HOP_HEADERS:
            continue
        # Let httpx handle accept-encoding; avoid confusing content-length.
        if k == "accept-encoding":
            continue
        out[k] = v_b.decode("latin-1")
    return out


def _filter_incoming_headers(headers: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in headers:
        lk = k.lower()
        if lk in _HOP_BY_HOP_HEADERS:
            continue
        if lk == "set-cookie":
            # upstream should not set cookies for API requests; drop defensively
            continue
        if lk == "content-encoding":
            # httpx automatically decompresses gzip/deflate responses, so remove this header
            # to avoid "incorrect header check" errors in clients like n8n
            continue
        out[k] = v
    return out


def _is_stream_request(request: Request) -> bool:
    # Gemini SSE commonly uses alt=sse query parameter.
    if request.query_params.get("alt", "").lower() == "sse":
        return True
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept.lower():
        return True
    return False


def _is_retryable_status(status_code: int) -> bool:
    # Conservative retry policy: transient failures and rate limits.
    if status_code in (408, 409, 425, 429):
        return True
    if 500 <= status_code <= 599:
        return True
    # Optional: some quota/permission errors are recoverable by switching keys.
    if status_code == 403:
        return True
    return False


def _extract_model_name_from_path(path: str) -> Optional[str]:
    # Expected: /v1beta/models/{model}:generateContent or /v1beta/models/{model}:streamGenerateContent
    try:
        marker = "/models/"
        idx = path.find(marker)
        if idx < 0:
            return None
        rest = path[idx + len(marker) :]
        # rest begins with "{model}..."
        model = rest.split(":", 1)[0].split("/", 1)[0]
        return model or None
    except Exception:
        return None


def _extract_file_references_from_body(body: bytes) -> list[str]:
    """
    Extract file references from request body.
    Files are referenced as fileData.fileUri in the contents parts.
    """
    file_names = []
    try:
        if not body:
            return file_names
        
        payload = json.loads(body)
        contents = payload.get("contents", [])
        
        for content in contents:
            if not isinstance(content, dict) or "parts" not in content:
                continue
            
            parts = content.get("parts", [])
            for part in parts:
                if not isinstance(part, dict) or "fileData" not in part:
                    continue
                
                file_data = part.get("fileData", {})
                if not isinstance(file_data, dict) or "fileUri" not in file_data:
                    continue
                
                file_uri = file_data.get("fileUri", "")
                # Extract file name from URI
                # Format: https://generativelanguage.googleapis.com/v1beta/files/{file_id}
                # or: files/{file_id} or files/local/{id}
                match = re.match(
                    rf"{re.escape(settings.BASE_URL)}/(files/.*)", file_uri
                )
                if match:
                    file_name = match.group(1)
                    file_names.append(file_name)
                    logger.info(f"Found file reference in request: {file_name}")
                elif file_uri.startswith("files/"):
                    # Direct file reference without full URL (includes files/local/...)
                    file_names.append(file_uri)
                    logger.info(f"Found direct file reference in request: {file_uri}")
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.debug(f"Failed to extract file references from body: {e}")
    
    return file_names


def _prepare_body_for_request_log(body: Optional[bytes], max_bytes: int) -> Optional[str]:
    """Decode and truncate body for request log storage. Returns None if body is None or empty."""
    if not body:
        return None
    try:
        s = body.decode("utf-8", errors="replace")
        if len(s) > max_bytes:
            s = s[:max_bytes] + "\n...(truncated)"
        return s
    except Exception:
        return None


async def _proxy_once(
    request: Request,
    upstream_url: str,
    outgoing_headers: Dict[str, str],
    timeout_s: float,
    stream: bool,
    body: Optional[bytes] = None,
) -> Tuple[int, Dict[str, str], bytes, Optional[AsyncGenerator[bytes, None]]]:
    """
    Execute a single upstream call.

    Returns: (status_code, headers, body, stream_iter)
    """
    method = request.method.upper()
    if body is None:
        body = await request.body()

    timeout = httpx.Timeout(timeout_s, read=timeout_s)

    # NOTE: For streaming, we must keep the AsyncClient alive for the duration of the stream.
    if stream:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        upstream_cm = client.stream(
            method=method,
            url=upstream_url,
            headers=outgoing_headers,
            content=body if body else None,
        )
        upstream_response = await upstream_cm.__aenter__()
        headers = _filter_incoming_headers(upstream_response.headers.items())

        async def gen() -> AsyncGenerator[bytes, None]:
            try:
                async for chunk in upstream_response.aiter_raw():
                    if chunk:
                        yield chunk
            finally:
                try:
                    await upstream_cm.__aexit__(None, None, None)
                finally:
                    await client.aclose()

        return upstream_response.status_code, headers, b"", gen()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        upstream_response = await client.request(
            method=method,
            url=upstream_url,
            headers=outgoing_headers,
            content=body if body else None,
        )
        headers = _filter_incoming_headers(upstream_response.headers.items())
        return upstream_response.status_code, headers, upstream_response.content, None


@router.api_route("/v1beta/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
@router.api_route("/gemini/v1beta/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def gemini_v1beta_proxy(
    request: Request,
    path: str,
    _allowed_token=Depends(security_service.verify_key_or_goog_api_key),
    key_manager: KeyManager = Depends(_get_key_manager),
):
    """
    Transparent reverse-proxy for Gemini v1beta endpoints.
    """
    start_time = time.perf_counter()
    request_datetime = datetime.datetime.now()

    # Normalize upstream path: ensure we forward to settings.BASE_URL (already includes /v1beta).
    upstream_base = settings.BASE_URL.rstrip("/")
    upstream_path = path.lstrip("/")

    # Build query params, always overriding 'key' with server-selected key.
    # Keep all other query params as-is.
    original_qp = dict(request.query_params)
    original_qp.pop("key", None)

    stream = _is_stream_request(request)

    # Capture model name for logs/stats; when not extractable, use request path
    _path_for_log = f"v1beta/{upstream_path}" if upstream_path else "v1beta/"
    extracted_model = _extract_model_name_from_path(f"/v1beta/{upstream_path}")
    model_name = (
        extracted_model
        or (_path_for_log[:100] if len(_path_for_log) <= 100 else _path_for_log[:97] + "...")
    )

    # Per-model RPM limit: wait until a slot is available (skip when no model in path)
    if settings.MODEL_RPM_LIMIT > 0 and extracted_model:
        await model_rpm_limiter.acquire(extracted_model, settings.MODEL_RPM_LIMIT)

    last_error: Optional[str] = None
    last_status: Optional[int] = None
    api_key: Optional[str] = None

    # Read request body once (can only be read once)
    request_body: Optional[bytes] = None
    if request.method in ("POST", "PUT", "PATCH"):
        request_body = await request.body()
    
    # Check for file references in the request body and get the appropriate API key
    has_file_references = False
    has_local_file_refs = False
    file_specific_api_key: Optional[str] = None
    if request_body:
        file_names = _extract_file_references_from_body(request_body)
        if file_names:
            has_file_references = True
            has_local_file_refs = any(
                fn.startswith("files/local/") for fn in file_names
            )
            logger.info(f"Request contains file references: {file_names}")
            if has_local_file_refs:
                # Local files: resolve in loop with current key each attempt; do not use DB key
                api_key = None
                file_specific_api_key = None
            else:
                # Use the API key from the first file (if multiple files, they should use the same key)
                file_api_key = await get_file_api_key(file_names[0])
                if file_api_key:
                    logger.info(
                        f"Using API key from file {file_names[0]}: {redact_key_for_logging(file_api_key)}"
                    )
                    api_key = file_api_key
                    file_specific_api_key = file_api_key
                else:
                    logger.warning(
                        f"No API key found for file {file_names[0]}, will use default key selection"
                    )

    # Prepare headers (copy most inbound headers through)
    outgoing_headers = _filter_outgoing_headers(request.scope.get("headers", []))
    # Apply configured custom headers (server-side override)
    if settings.CUSTOM_HEADERS:
        for hk, hv in settings.CUSTOM_HEADERS.items():
            outgoing_headers[str(hk).lower()] = str(hv)

    for attempt in range(settings.MAX_RETRIES):
        retries = attempt + 1

        # Sleep before retry (skip on first attempt)
        if attempt > 0 and settings.RETRY_SLEEP_SECONDS > 0:
            logger.info(
                f"Waiting {settings.RETRY_SLEEP_SECONDS}s before retry {retries}/{settings.MAX_RETRIES}"
            )
            await asyncio.sleep(settings.RETRY_SLEEP_SECONDS)

        api_key = await key_manager.get_next_working_key() if api_key is None else api_key

        # For local file refs: resolve (upload to Gemini + substitute in body) with current key each attempt
        body_to_send = request_body
        if has_local_file_refs and request_body and api_key:
            try:
                body_to_send, _ = await resolve_local_files_in_body(request_body, api_key)
            except Exception as e:
                logger.warning(f"Resolve local files failed: {e}")
                last_error = (str(e) or repr(e) or type(e).__name__).strip() or "Local resolve error (no details)"
                last_status = None
                request_msg_parsed = None
                if settings.ERROR_LOG_RECORD_REQUEST_BODY and request_body:
                    try:
                        request_msg_parsed = json.loads(
                            request_body.decode("utf-8", errors="replace")
                        )
                    except json.JSONDecodeError:
                        request_msg_parsed = {"_raw_preview": request_body[:500].decode("utf-8", errors="replace")}
                attempt_time = datetime.datetime.now()
                await add_error_log(
                    gemini_key=api_key,
                    model_name=model_name,
                    error_type="gemini-proxy-local-resolve",
                    error_log=last_error,
                    error_code=None,
                    request_msg=request_msg_parsed,
                    request_datetime=attempt_time,
                )
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                req_len = len(body_to_send) if body_to_send else None
                req_body_str = _prepare_body_for_request_log(body_to_send or request_body, settings.REQUEST_LOG_BODY_MAX_BYTES) if settings.REQUEST_LOG_RECORD_BODY else None
                await add_request_log(
                    model_name=model_name,
                    api_key=api_key,
                    is_success=False,
                    status_code=None,
                    latency_ms=latency_ms,
                    request_time=attempt_time,
                    request_content_length=req_len,
                    request_body=req_body_str,
                )
                api_key = await key_manager.handle_api_failure(api_key, retries)
                if not api_key:
                    break
                continue

        qp = dict(original_qp)
        qp["key"] = api_key
        upstream_url = str(httpx.URL(f"{upstream_base}/{upstream_path}").copy_with(params=qp))

        try:
            status_code, headers, body, stream_iter = await _proxy_once(
                request=request,
                upstream_url=upstream_url,
                outgoing_headers=outgoing_headers,
                timeout_s=settings.TIME_OUT,
                stream=stream,
                body=body_to_send,
            )

            last_status = status_code

            # If not retryable, return immediately.
            if not _is_retryable_status(status_code):
                is_success = 200 <= status_code < 300
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                req_len = len(body_to_send) if body_to_send else None
                resp_len = len(body) if body else None
                token_count = None
                if is_success and body and not stream:
                    token_count = extract_total_token_count_from_gemini_response(response_body=body)
                req_body_str = _prepare_body_for_request_log(body_to_send, settings.REQUEST_LOG_BODY_MAX_BYTES) if settings.REQUEST_LOG_RECORD_BODY else None
                resp_body_str = _prepare_body_for_request_log(body, settings.REQUEST_LOG_BODY_MAX_BYTES) if settings.REQUEST_LOG_RECORD_BODY else None
                await add_request_log(
                    model_name=model_name,
                    api_key=api_key,
                    is_success=is_success,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    request_time=request_datetime,
                    request_content_length=req_len,
                    response_content_length=resp_len,
                    total_token_count=token_count,
                    request_body=req_body_str,
                    response_body=resp_body_str,
                )

                if stream and stream_iter is not None:
                    # Ensure SSE content-type if upstream didn't provide it
                    media_type = headers.get("content-type") or "text/event-stream"
                    return StreamingResponse(
                        stream_iter, status_code=status_code, headers=headers, media_type=media_type
                    )

                return Response(content=body, status_code=status_code, headers=headers)

            # Retryable status: log error and switch key (unless last attempt)
            # If upstream is rate limiting this model, apply a cooldown for subsequent requests.
            if status_code == 429 and extracted_model:
                await model_rpm_limiter.trigger_cooldown(extracted_model, 60.0)
            last_error = body.decode("utf-8", errors="replace") if body else f"HTTP {status_code}"
            request_msg_parsed = None
            if settings.ERROR_LOG_RECORD_REQUEST_BODY and body_to_send:
                try:
                    request_msg_parsed = json.loads(
                        body_to_send.decode("utf-8", errors="replace")
                    )
                except json.JSONDecodeError:
                    request_msg_parsed = {"_raw_preview": body_to_send[:500].decode("utf-8", errors="replace")}
            attempt_time = datetime.datetime.now()
            await add_error_log(
                gemini_key=api_key,
                model_name=model_name,
                error_type="gemini-proxy",
                error_log=last_error,
                error_code=status_code,
                request_msg=request_msg_parsed,
                request_datetime=attempt_time,
            )
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            req_len = len(body_to_send) if body_to_send else None
            resp_len = len(body) if body else None
            req_body_str = _prepare_body_for_request_log(body_to_send, settings.REQUEST_LOG_BODY_MAX_BYTES) if settings.REQUEST_LOG_RECORD_BODY else None
            resp_body_str = _prepare_body_for_request_log(body, settings.REQUEST_LOG_BODY_MAX_BYTES) if settings.REQUEST_LOG_RECORD_BODY else None
            await add_request_log(
                model_name=model_name,
                api_key=api_key,
                is_success=False,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=attempt_time,
                request_content_length=req_len,
                response_content_length=resp_len,
                request_body=req_body_str,
                response_body=resp_body_str,
            )

            # If we're using a file-specific API key (Gemini file), don't switch keys on retry.
            # For local file refs we always switch key and re-upload on retry.
            if has_file_references and not has_local_file_refs and file_specific_api_key and api_key == file_specific_api_key:
                logger.warning(
                    f"Request with file references failed with API key {redact_key_for_logging(api_key)}. "
                    f"Cannot switch keys as file can only be accessed with its original key."
                )
                # Still allow retry with the same key in case of transient errors
                if retries >= settings.MAX_RETRIES:
                    break
            else:
                api_key = await key_manager.handle_api_failure(api_key, retries)
                if not api_key:
                    break

        except httpx.RequestError as e:
            # Ensure we always have a non-empty error message (some exceptions have empty str())
            last_error = (str(e) or repr(e) or type(e).__name__).strip() or "Network error (no details)"
            last_status = None
            # Safely parse request_msg to avoid losing error record on JSON decode failure
            request_msg_parsed = None
            if settings.ERROR_LOG_RECORD_REQUEST_BODY and request_body:
                try:
                    request_msg_parsed = json.loads(
                        request_body.decode("utf-8", errors="replace")
                    )
                except json.JSONDecodeError:
                    request_msg_parsed = {"_raw_preview": request_body[:500].decode("utf-8", errors="replace")}
            attempt_time = datetime.datetime.now()
            await add_error_log(
                gemini_key=api_key,
                model_name=model_name,
                error_type="gemini-proxy-network",
                error_log=last_error,
                error_code=None,
                request_msg=request_msg_parsed,
                request_datetime=attempt_time,
            )
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            req_len = len(request_body or body_to_send) if (request_body or body_to_send) else None
            req_body_str = _prepare_body_for_request_log(request_body or body_to_send, settings.REQUEST_LOG_BODY_MAX_BYTES) if settings.REQUEST_LOG_RECORD_BODY else None
            await add_request_log(
                model_name=model_name,
                api_key=api_key,
                is_success=False,
                status_code=None,
                latency_ms=latency_ms,
                request_time=attempt_time,
                request_content_length=req_len,
                request_body=req_body_str,
            )
            # If we're using a file-specific API key (Gemini file), don't switch keys on retry
            if has_file_references and not has_local_file_refs and file_specific_api_key and api_key == file_specific_api_key:
                logger.warning(
                    f"Request with file references failed with network error. "
                    f"Cannot switch keys as file can only be accessed with its original key."
                )
                if retries >= settings.MAX_RETRIES:
                    break
            else:
                api_key = await key_manager.handle_api_failure(api_key or "", retries)
                if not api_key:
                    break

    # Final failure: return last observed status/body if available, else 502.
    # (Each failed attempt already logged to RequestLog above; no duplicate here.)

    if last_status is not None and last_error is not None:
        return Response(
            content=last_error.encode("utf-8"),
            status_code=last_status,
            media_type="application/json" if last_error.lstrip().startswith("{") else "text/plain",
        )

    return Response(
        content=b'{"error":{"message":"Upstream request failed"}}',
        status_code=502,
        media_type="application/json",
    )

