import asyncio
from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.config.config import settings
from app.core.constants import API_VERSION
from app.core.security import SecurityService
from app.domain.gemini_models import (
    GeminiBatchEmbedRequest,
    GeminiEmbedRequest,
    GeminiRequest,
)
from app.handler.error_handler import handle_route_errors
from app.handler.retry_handler import RetryHandler
from app.log.logger import get_gemini_logger
from app.service.chat.gemini_chat_service import GeminiChatService
from app.service.embedding.gemini_embedding_service import GeminiEmbeddingService
from app.service.key.key_manager import KeyManager, get_key_manager_instance
from app.service.model.model_service import ModelService
from app.service.tts.native.tts_routes import get_tts_chat_service
from app.utils.helpers import redact_key_for_logging

router = APIRouter(prefix=f"/gemini/{API_VERSION}")
router_v1beta = APIRouter(prefix=f"/{API_VERSION}")
logger = get_gemini_logger()

security_service = SecurityService()
model_service = ModelService()


async def get_key_manager():
    """获取密钥管理器实例"""
    return await get_key_manager_instance(settings.API_KEYS, settings.VERTEX_API_KEYS)


async def get_next_working_key(key_manager: KeyManager = Depends(get_key_manager)):
    """获取下一个可用的API密钥"""
    return await key_manager.get_next_working_key()


async def get_chat_service(key_manager: KeyManager = Depends(get_key_manager)):
    """获取Gemini聊天服务实例"""
    return GeminiChatService(settings.BASE_URL, key_manager)


async def get_embedding_service(key_manager: KeyManager = Depends(get_key_manager)):
    """获取Gemini嵌入服务实例"""
    return GeminiEmbeddingService(settings.BASE_URL, key_manager)


@router.get("/models")
@router_v1beta.get("/models")
async def list_models(
    allowed_token=Depends(security_service.verify_key_or_goog_api_key),
    key_manager: KeyManager = Depends(get_key_manager),
):
    """获取可用的 Gemini 模型列表，并根据配置添加衍生模型（搜索、图像、非思考）。"""
    operation_name = "list_gemini_models"
    logger.info("-" * 50 + operation_name + "-" * 50)
    logger.info("Handling Gemini models list request")

    try:
        api_key = await key_manager.get_random_valid_key()
        if not api_key:
            raise HTTPException(
                status_code=503, detail="No valid API keys available to fetch models."
            )
        logger.info(f"Using allowed token: {allowed_token}")
        logger.info(f"Using API key: {redact_key_for_logging(api_key)}")

        models_data = await model_service.get_gemini_models(api_key)
        if not models_data or "models" not in models_data:
            raise HTTPException(
                status_code=500, detail="Failed to fetch base models list."
            )

        models_json = deepcopy(models_data)
        model_mapping = {
            x.get("name", "").split("/", maxsplit=1)[-1]: x
            for x in models_json.get("models", [])
        }

        def add_derived_model(base_name, suffix, display_suffix):
            model = model_mapping.get(base_name)
            if not model:
                logger.warning(
                    f"Base model '{base_name}' not found for derived model '{suffix}'."
                )
                return
            item = deepcopy(model)
            item["name"] = f"models/{base_name}{suffix}"
            display_name = f'{item.get("displayName", base_name)}{display_suffix}'
            item["displayName"] = display_name
            item["description"] = display_name
            models_json["models"].append(item)

        if settings.SEARCH_MODELS:
            for name in settings.SEARCH_MODELS:
                add_derived_model(name, "-search", " For Search")
        if settings.IMAGE_MODELS:
            for name in settings.IMAGE_MODELS:
                add_derived_model(name, "-image", " For Image")
        if settings.THINKING_MODELS:
            for name in settings.THINKING_MODELS:
                add_derived_model(name, "-non-thinking", " Non Thinking")

        logger.info("Gemini models list request successful")
        return models_json
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Error getting Gemini models list: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching Gemini models list",
        ) from e


@router.post("/models/{model_name}:generateContent")
@router_v1beta.post("/models/{model_name}:generateContent")
@RetryHandler(key_arg="api_key")
async def generate_content(
    model_name: str,
    request: GeminiRequest,
    allowed_token=Depends(security_service.verify_key_or_goog_api_key),
    api_key: str = Depends(get_next_working_key),
    key_manager: KeyManager = Depends(get_key_manager),
    chat_service: GeminiChatService = Depends(get_chat_service),
):
    """处理 Gemini 非流式内容生成请求。"""
    operation_name = "gemini_generate_content"
    async with handle_route_errors(
        logger, operation_name, failure_message="Content generation failed"
    ):
        logger.info(
            f"Handling Gemini content generation request for model: {model_name}"
        )
        logger.debug(f"Request: \n{request.model_dump_json(indent=2)}")

        # 检测是否为原生Gemini TTS请求
        is_native_tts = False
        if "tts" in model_name.lower() and request.generationConfig:
            # 直接从解析后的request对象获取TTS配置
            response_modalities = request.generationConfig.responseModalities or []
            speech_config = request.generationConfig.speechConfig or {}

            # 如果包含AUDIO模态和语音配置，则认为是原生TTS请求
            if "AUDIO" in response_modalities and speech_config:
                is_native_tts = True
                logger.info("Detected native Gemini TTS request")
                logger.info(f"TTS responseModalities: {response_modalities}")
                logger.info(f"TTS speechConfig: {speech_config}")

        logger.info(f"Using allowed token: {allowed_token}")
        logger.info(f"Using API key: {redact_key_for_logging(api_key)}")

        if not await model_service.check_model_support(model_name):
            raise HTTPException(
                status_code=400, detail=f"Model {model_name} is not supported"
            )

        # 所有原生TTS请求都使用TTS增强服务
        if is_native_tts:
            try:
                logger.info("Using native TTS enhanced service")
                tts_service = await get_tts_chat_service(key_manager)
                response = await tts_service.generate_content(
                    model=model_name, request=request, api_key=api_key
                )
                return response
            except Exception as e:
                logger.warning(
                    f"Native TTS processing failed, falling back to standard service: {e}"
                )

        # 使用标准服务处理所有其他请求（非TTS）
        response = await chat_service.generate_content(
            model=model_name, request=request, api_key=api_key
        )
        return response


@router.post("/models/{model_name}:streamGenerateContent")
@router_v1beta.post("/models/{model_name}:streamGenerateContent")
@RetryHandler(key_arg="api_key")
async def stream_generate_content(
    model_name: str,
    request: GeminiRequest,
    allowed_token=Depends(security_service.verify_key_or_goog_api_key),
    api_key: str = Depends(get_next_working_key),
    key_manager: KeyManager = Depends(get_key_manager),
    chat_service: GeminiChatService = Depends(get_chat_service),
):
    """处理 Gemini 流式内容生成请求。"""
    operation_name = "gemini_stream_generate_content"
    async with handle_route_errors(
        logger, operation_name, failure_message="Streaming request initiation failed"
    ):
        logger.info(
            f"Handling Gemini streaming content generation for model: {model_name}"
        )
        logger.debug(f"Request: \n{request.model_dump_json(indent=2)}")
        logger.info(f"Using allowed token: {allowed_token}")
        logger.info(f"Using API key: {redact_key_for_logging(api_key)}")

        if not await model_service.check_model_support(model_name):
            raise HTTPException(
                status_code=400, detail=f"Model {model_name} is not supported"
            )

        raw_stream = chat_service.stream_generate_content(
            model=model_name, request=request, api_key=api_key
        )
        try:
            # 尝试获取第一条数据，判断是正常 SSE（data: 前缀）还是错误 JSON
            first_chunk = await raw_stream.__anext__()
        except StopAsyncIteration:
            # 如果流直接结束，退回标准 SSE 输出
            return StreamingResponse(raw_stream, media_type="text/event-stream")
        except Exception as e:
            # 初始化流异常，直接返回 500 错误
            return JSONResponse(
                content={"error": {"code": e.args[0], "message": e.args[1]}},
                status_code=e.args[0],
            )

        # 如果以 "data:" 开头，代表正常 SSE，将首块和后续块一起发送
        if isinstance(first_chunk, str) and first_chunk.startswith("data:"):

            async def combined():
                yield first_chunk
                async for chunk in raw_stream:
                    yield chunk

            return StreamingResponse(combined(), media_type="text/event-stream")


@router.post("/models/{model_name}:countTokens")
@router_v1beta.post("/models/{model_name}:countTokens")
@RetryHandler(key_arg="api_key")
async def count_tokens(
    model_name: str,
    request: GeminiRequest,
    allowed_token=Depends(security_service.verify_key_or_goog_api_key),
    api_key: str = Depends(get_next_working_key),
    key_manager: KeyManager = Depends(get_key_manager),
    chat_service: GeminiChatService = Depends(get_chat_service),
):
    """处理 Gemini token 计数请求。"""
    operation_name = "gemini_count_tokens"
    async with handle_route_errors(
        logger, operation_name, failure_message="Token counting failed"
    ):
        logger.info(f"Handling Gemini token count request for model: {model_name}")
        logger.debug(f"Request: \n{request.model_dump_json(indent=2)}")
        logger.info(f"Using allowed token: {allowed_token}")
        logger.info(f"Using API key: {redact_key_for_logging(api_key)}")

        if not await model_service.check_model_support(model_name):
            raise HTTPException(
                status_code=400, detail=f"Model {model_name} is not supported"
            )

        response = await chat_service.count_tokens(
            model=model_name, request=request, api_key=api_key
        )
        return response


@router.post("/models/{model_name}:embedContent")
@router_v1beta.post("/models/{model_name}:embedContent")
@RetryHandler(key_arg="api_key")
async def embed_content(
    model_name: str,
    request: GeminiEmbedRequest,
    allowed_token=Depends(security_service.verify_key_or_goog_api_key),
    api_key: str = Depends(get_next_working_key),
    key_manager: KeyManager = Depends(get_key_manager),
    embedding_service: GeminiEmbeddingService = Depends(get_embedding_service),
):
    """处理 Gemini 单一嵌入请求"""
    operation_name = "gemini_embed_content"
    async with handle_route_errors(
        logger, operation_name, failure_message="Embedding content generation failed"
    ):
        logger.info(f"Handling Gemini embedding request for model: {model_name}")
        logger.debug(f"Request: \n{request.model_dump_json(indent=2)}")
        logger.info(f"Using allowed token: {allowed_token}")
        logger.info(f"Using API key: {redact_key_for_logging(api_key)}")

        if not await model_service.check_model_support(model_name):
            raise HTTPException(
                status_code=400, detail=f"Model {model_name} is not supported"
            )

        response = await embedding_service.embed_content(
            model=model_name, request=request, api_key=api_key
        )
        return response


@router.post("/models/{model_name}:batchEmbedContents")
@router_v1beta.post("/models/{model_name}:batchEmbedContents")
@RetryHandler(key_arg="api_key")
async def batch_embed_contents(
    model_name: str,
    request: GeminiBatchEmbedRequest,
    allowed_token=Depends(security_service.verify_key_or_goog_api_key),
    api_key: str = Depends(get_next_working_key),
    key_manager: KeyManager = Depends(get_key_manager),
    embedding_service: GeminiEmbeddingService = Depends(get_embedding_service),
):
    """处理 Gemini 批量嵌入请求"""
    operation_name = "gemini_batch_embed_contents"
    async with handle_route_errors(
        logger,
        operation_name,
        failure_message="Batch embedding content generation failed",
    ):
        logger.info(f"Handling Gemini batch embedding request for model: {model_name}")
        logger.debug(f"Request: \n{request.model_dump_json(indent=2)}")
        logger.info(f"Using allowed token: {allowed_token}")
        logger.info(f"Using API key: {redact_key_for_logging(api_key)}")

        if not await model_service.check_model_support(model_name):
            raise HTTPException(
                status_code=400, detail=f"Model {model_name} is not supported"
            )

        response = await embedding_service.batch_embed_contents(
            model=model_name, request=request, api_key=api_key
        )
        return response
