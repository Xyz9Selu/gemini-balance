"""
Admin key tools routes (verify/reset) used by the web UI.

These endpoints are NOT upstream proxy calls. They operate on the server-managed
key pool and are kept stable for the existing frontend.
"""

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.config.config import settings
from app.core.constants import API_VERSION
from app.domain.gemini_models import GeminiContent, GeminiRequest, ResetSelectedKeysRequest, VerifySelectedKeysRequest
from app.log.logger import get_gemini_logger
from app.service.chat.gemini_chat_service import GeminiChatService
from app.service.key.key_manager import KeyManager, get_key_manager_instance
from app.utils.helpers import redact_key_for_logging

logger = get_gemini_logger()

router = APIRouter(prefix=f"/gemini/{API_VERSION}")
router_v1beta = APIRouter(prefix=f"/{API_VERSION}")


async def get_key_manager():
    # Be defensive: if lifespan init was skipped/failed, initialize lazily.
    return await get_key_manager_instance(settings.API_KEYS, settings.VERTEX_API_KEYS)


async def get_chat_service(key_manager: KeyManager = Depends(get_key_manager)):
    return GeminiChatService(settings.BASE_URL, key_manager)


@router.post("/reset-all-fail-counts")
@router_v1beta.post("/reset-all-fail-counts")
async def reset_all_key_fail_counts(
    key_type: str = None, key_manager: KeyManager = Depends(get_key_manager)
):
    """批量重置Gemini API密钥的失败计数，可选择性地仅重置有效或无效密钥"""
    logger.info("-" * 50 + "reset_all_gemini_key_fail_counts" + "-" * 50)
    logger.info(f"Received reset request with key_type: {key_type}")

    try:
        keys_by_status = await key_manager.get_keys_by_status()
        valid_keys = keys_by_status.get("valid_keys", {})
        invalid_keys = keys_by_status.get("invalid_keys", {})

        keys_to_reset = []
        if key_type == "valid":
            keys_to_reset = list(valid_keys.keys())
            logger.info(f"Resetting only valid keys, count: {len(keys_to_reset)}")
        elif key_type == "invalid":
            keys_to_reset = list(invalid_keys.keys())
            logger.info(f"Resetting only invalid keys, count: {len(keys_to_reset)}")
        else:
            await key_manager.reset_failure_counts()
            return JSONResponse({"success": True, "message": "所有密钥的失败计数已重置"})

        for key in keys_to_reset:
            await key_manager.reset_key_failure_count(key)

        return JSONResponse(
            {
                "success": True,
                "message": f"{key_type}密钥的失败计数已重置",
                "reset_count": len(keys_to_reset),
            }
        )
    except Exception as e:
        logger.error(f"Failed to reset key failure counts: {str(e)}")
        return JSONResponse(
            {"success": False, "message": f"批量重置失败: {str(e)}"}, status_code=500
        )


@router.post("/reset-selected-fail-counts")
@router_v1beta.post("/reset-selected-fail-counts")
async def reset_selected_key_fail_counts(
    request: ResetSelectedKeysRequest,
    key_manager: KeyManager = Depends(get_key_manager),
):
    """批量重置选定Gemini API密钥的失败计数"""
    logger.info("-" * 50 + "reset_selected_gemini_key_fail_counts" + "-" * 50)
    keys_to_reset = request.keys
    key_type = request.key_type
    logger.info(
        f"Received reset request for {len(keys_to_reset)} selected {key_type} keys."
    )

    if not keys_to_reset:
        return JSONResponse(
            {"success": False, "message": "没有提供需要重置的密钥"}, status_code=400
        )

    reset_count = 0
    errors = []

    try:
        for key in keys_to_reset:
            try:
                result = await key_manager.reset_key_failure_count(key)
                if result:
                    reset_count += 1
                else:
                    logger.warning(
                        f"Key not found during selective reset: {redact_key_for_logging(key)}"
                    )
            except Exception as key_error:
                logger.error(
                    f"Error resetting key {redact_key_for_logging(key)}: {str(key_error)}"
                )
                errors.append(f"Key {key}: {str(key_error)}")

        if errors:
            error_message = f"批量重置完成，但出现错误: {'; '.join(errors)}"
            final_success = reset_count > 0
            status_code = 207 if final_success and errors else 500
            return JSONResponse(
                {
                    "success": final_success,
                    "message": error_message,
                    "reset_count": reset_count,
                },
                status_code=status_code,
            )

        return JSONResponse(
            {
                "success": True,
                "message": f"成功重置 {reset_count} 个选定 {key_type} 密钥的失败计数",
                "reset_count": reset_count,
            }
        )
    except Exception as e:
        logger.error(
            f"Failed to process reset selected key failure counts request: {str(e)}"
        )
        return JSONResponse(
            {"success": False, "message": f"批量重置处理失败: {str(e)}"},
            status_code=500,
        )


@router.post("/reset-fail-count/{api_key}")
@router_v1beta.post("/reset-fail-count/{api_key}")
async def reset_key_fail_count(
    api_key: str, key_manager: KeyManager = Depends(get_key_manager)
):
    """重置指定Gemini API密钥的失败计数"""
    logger.info("-" * 50 + "reset_gemini_key_fail_count" + "-" * 50)
    logger.info(
        f"Resetting failure count for API key: {redact_key_for_logging(api_key)}"
    )

    try:
        result = await key_manager.reset_key_failure_count(api_key)
        if result:
            return JSONResponse({"success": True, "message": "失败计数已重置"})
        return JSONResponse({"success": False, "message": "未找到指定密钥"}, status_code=404)
    except Exception as e:
        logger.error(f"Failed to reset key failure count: {str(e)}")
        return JSONResponse(
            {"success": False, "message": f"重置失败: {str(e)}"}, status_code=500
        )


@router.post("/verify-key/{api_key}")
@router_v1beta.post("/verify-key/{api_key}")
async def verify_key(
    api_key: str,
    chat_service: GeminiChatService = Depends(get_chat_service),
    key_manager: KeyManager = Depends(get_key_manager),
):
    """验证Gemini API密钥的有效性"""
    logger.info("-" * 50 + "verify_gemini_key" + "-" * 50)
    logger.info("Verifying API key validity")

    try:
        gemini_request = GeminiRequest(
            contents=[
                GeminiContent(
                    role="user",
                    parts=[{"text": "hi"}],
                )
            ],
            generation_config={"temperature": 0.7, "topP": 1.0, "maxOutputTokens": 10},
        )

        response = await chat_service.generate_content(settings.TEST_MODEL, gemini_request, api_key)
        if response:
            await key_manager.reset_key_failure_count(api_key)
            return JSONResponse({"status": "valid"})
    except Exception as e:
        logger.error(f"Key verification failed: {str(e)}")

        async with key_manager.failure_count_lock:
            if api_key in key_manager.key_failure_counts:
                key_manager.key_failure_counts[api_key] += 1
                logger.warning(
                    f"Verification exception for key: {redact_key_for_logging(api_key)}, incrementing failure count"
                )

        return JSONResponse({"status": "invalid", "error": e.args[1] if len(e.args) > 1 else str(e)})


@router.post("/verify-selected-keys")
@router_v1beta.post("/verify-selected-keys")
async def verify_selected_keys(
    request: VerifySelectedKeysRequest,
    chat_service: GeminiChatService = Depends(get_chat_service),
    key_manager: KeyManager = Depends(get_key_manager),
):
    """批量验证选定Gemini API密钥的有效性"""
    logger.info("-" * 50 + "verify_selected_gemini_keys" + "-" * 50)
    keys_to_verify = request.keys
    logger.info(f"Received verification request for {len(keys_to_verify)} selected keys.")

    if not keys_to_verify:
        return JSONResponse(
            {"success": False, "message": "没有提供需要验证的密钥"}, status_code=400
        )

    successful_keys = []
    failed_keys = {}

    async def _verify_single_key(one_key: str):
        nonlocal successful_keys, failed_keys
        try:
            gemini_request = GeminiRequest(
                contents=[GeminiContent(role="user", parts=[{"text": "hi"}])],
                generation_config={
                    "temperature": 0.7,
                    "topP": 1.0,
                    "maxOutputTokens": 10,
                },
            )
            await chat_service.generate_content(settings.TEST_MODEL, gemini_request, one_key)
            successful_keys.append(one_key)
            await key_manager.reset_key_failure_count(one_key)
            return one_key, "valid", None
        except Exception as e:
            error_message = e.args[1] if len(e.args) > 1 else str(e)
            logger.warning(
                f"Key verification failed for {redact_key_for_logging(one_key)}: {error_message}"
            )
            async with key_manager.failure_count_lock:
                if one_key in key_manager.key_failure_counts:
                    key_manager.key_failure_counts[one_key] += 1
                else:
                    key_manager.key_failure_counts[one_key] = 1
            failed_keys[one_key] = {
                "error_message": error_message,
                "error_code": e.args[0] if len(e.args) > 0 and isinstance(e.args[0], int) else None,
            }
            return one_key, "invalid", error_message

    tasks = [_verify_single_key(k) for k in keys_to_verify]
    await asyncio.gather(*tasks, return_exceptions=True)

    valid_count = len(successful_keys)
    invalid_count = len(failed_keys)
    logger.info(f"Bulk verification finished. Valid: {valid_count}, Invalid: {invalid_count}")

    if failed_keys:
        message = f"批量验证完成。成功: {valid_count}, 失败: {invalid_count}。"
        return JSONResponse(
            {
                "success": True,
                "message": message,
                "successful_keys": successful_keys,
                "failed_keys": failed_keys,
                "valid_count": valid_count,
                "invalid_count": invalid_count,
            }
        )

    message = f"批量验证成功完成。所有 {valid_count} 个密钥均有效。"
    return JSONResponse(
        {
            "success": True,
            "message": message,
            "successful_keys": successful_keys,
            "failed_keys": {},
            "valid_count": valid_count,
            "invalid_count": 0,
        }
    )

