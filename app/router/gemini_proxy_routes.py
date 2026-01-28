"""
Gemini transparent transmission (raw reverse-proxy) routes.

This router forwards any /v1beta/** (and /gemini/v1beta/**) request to the upstream
Gemini Generative Language API, injecting a server-managed API key and performing
key switching retries on transient failures.
"""

from __future__ import annotations

import datetime
import time
from typing import AsyncGenerator, Dict, Iterable, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from app.config.config import settings
from app.core.security import SecurityService
from app.database.services import add_error_log, add_request_log
from app.log.logger import get_gemini_logger
from app.service.key.key_manager import KeyManager, get_key_manager_instance

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


async def _proxy_once(
    request: Request,
    upstream_url: str,
    outgoing_headers: Dict[str, str],
    timeout_s: float,
    stream: bool,
) -> Tuple[int, Dict[str, str], bytes, Optional[AsyncGenerator[bytes, None]]]:
    """
    Execute a single upstream call.

    Returns: (status_code, headers, body, stream_iter)
    """
    method = request.method.upper()
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

    # Capture model name for logs/stats
    model_name = _extract_model_name_from_path(f"/v1beta/{upstream_path}") or "gemini-proxy"

    last_error: Optional[str] = None
    last_status: Optional[int] = None
    api_key: Optional[str] = None

    # Prepare headers (copy most inbound headers through)
    outgoing_headers = _filter_outgoing_headers(request.scope.get("headers", []))
    # Apply configured custom headers (server-side override)
    if settings.CUSTOM_HEADERS:
        for hk, hv in settings.CUSTOM_HEADERS.items():
            outgoing_headers[str(hk).lower()] = str(hv)

    for attempt in range(settings.MAX_RETRIES):
        retries = attempt + 1
        api_key = await key_manager.get_next_working_key() if api_key is None else api_key

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
            )

            last_status = status_code

            # If not retryable, return immediately.
            if not _is_retryable_status(status_code):
                is_success = 200 <= status_code < 300
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                await add_request_log(
                    model_name=model_name,
                    api_key=api_key,
                    is_success=is_success,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    request_time=request_datetime,
                )

                if stream and stream_iter is not None:
                    # Ensure SSE content-type if upstream didn't provide it
                    media_type = headers.get("content-type") or "text/event-stream"
                    return StreamingResponse(
                        stream_iter, status_code=status_code, headers=headers, media_type=media_type
                    )

                return Response(content=body, status_code=status_code, headers=headers)

            # Retryable status: log error and switch key (unless last attempt)
            last_error = body.decode("utf-8", errors="replace") if body else f"HTTP {status_code}"
            await add_error_log(
                gemini_key=api_key,
                model_name=model_name,
                error_type="gemini-proxy",
                error_log=last_error,
                error_code=status_code,
                request_msg=(await request.body()) if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
                request_datetime=request_datetime,
            )

            api_key = await key_manager.handle_api_failure(api_key, retries)
            if not api_key:
                break

        except httpx.RequestError as e:
            last_error = str(e)
            last_status = None
            await add_error_log(
                gemini_key=api_key,
                model_name=model_name,
                error_type="gemini-proxy-network",
                error_log=last_error,
                error_code=None,
                request_msg=(await request.body()) if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
                request_datetime=request_datetime,
            )
            api_key = await key_manager.handle_api_failure(api_key or "", retries)
            if not api_key:
                break

    # Final failure: return last observed status/body if available, else 502.
    latency_ms = int((time.perf_counter() - start_time) * 1000)
    await add_request_log(
        model_name=model_name,
        api_key=api_key,
        is_success=False,
        status_code=last_status,
        latency_ms=latency_ms,
        request_time=request_datetime,
    )

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

