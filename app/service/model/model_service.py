from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config.config import settings
from app.log.logger import get_model_logger
from app.service.client.api_client import GeminiApiClient

logger = get_model_logger()


class ModelService:
    async def get_gemini_models(self, api_key: str) -> Optional[Dict[str, Any]]:
        api_client = GeminiApiClient(base_url=settings.BASE_URL)
        gemini_models = await api_client.get_models(api_key)

        if gemini_models is None:
            logger.error("从 API 客户端获取模型列表失败。")
            return None

        try:
            return gemini_models
        except Exception as e:
            logger.error(f"处理模型列表时出错: {e}")
            return None

    async def get_gemini_openai_models(self, api_key: str) -> Optional[Dict[str, Any]]:
        """获取 Gemini 模型并转换为 OpenAI 格式"""
        gemini_models = await self.get_gemini_models(api_key)
        if gemini_models is None:
            return None
        
        return await self.convert_to_openai_models_format(gemini_models)

    async def convert_to_openai_models_format(
        self, gemini_models: Dict[str, Any]
    ) -> Dict[str, Any]:
        openai_format = {"object": "list", "data": [], "success": True}

        for model in gemini_models.get("models", []):
            model_id = model["name"].split("/")[-1]
            openai_model = {
                "id": model_id,
                "object": "model",
                "created": int(datetime.now(timezone.utc).timestamp()),
                "owned_by": "google",
                "permission": [],
                "root": model["name"],
                "parent": None,
            }
            openai_format["data"].append(openai_model)

        return openai_format

    async def check_model_support(self, model: str) -> bool:
        if not model or not isinstance(model, str):
            return False
        return bool(model.strip())
