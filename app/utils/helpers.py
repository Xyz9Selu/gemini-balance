"""
通用工具函数模块
"""

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.core.constants import DATA_URL_PATTERN, IMAGE_URL_PATTERN, VALID_IMAGE_RATIOS

helper_logger = logging.getLogger("app.utils")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_FILE_PATH = PROJECT_ROOT / "VERSION"


def extract_mime_type_and_data(base64_string: str) -> Tuple[Optional[str], str]:
    """
    从 base64 字符串中提取 MIME 类型和数据

    Args:
        base64_string: 可能包含 MIME 类型信息的 base64 字符串

    Returns:
        tuple: (mime_type, encoded_data)
    """
    # 检查字符串是否以 "data:" 格式开始
    if base64_string.startswith("data:"):
        # 提取 MIME 类型和数据
        pattern = DATA_URL_PATTERN
        match = re.match(pattern, base64_string)
        if match:
            mime_type = (
                "image/jpeg" if match.group(1) == "image/jpg" else match.group(1)
            )
            encoded_data = match.group(2)
            return mime_type, encoded_data

    # 如果不是预期格式，假定它只是数据部分
    return None, base64_string


def convert_image_to_base64(url: str) -> str:
    """
    将图片URL转换为base64编码

    Args:
        url: 图片URL

    Returns:
        str: base64编码的图片数据

    Raises:
        Exception: 如果获取图片失败
    """
    response = requests.get(url)
    if response.status_code == 200:
        # 将图片内容转换为base64
        img_data = base64.b64encode(response.content).decode("utf-8")
        return img_data
    else:
        raise Exception(f"Failed to fetch image: {response.status_code}")


def format_json_response(data: Dict[str, Any], indent: int = 2) -> str:
    """
    格式化JSON响应

    Args:
        data: 要格式化的数据
        indent: 缩进空格数

    Returns:
        str: 格式化后的JSON字符串
    """
    return json.dumps(data, indent=indent, ensure_ascii=False)


def parse_prompt_parameters(
    prompt: str, default_ratio: str = "1:1"
) -> Tuple[str, int, str]:
    """
    从prompt中解析参数

    支持的格式:
    - {n:数量} 例如: {n:2} 生成2张图片
    - {ratio:比例} 例如: {ratio:16:9} 使用16:9比例

    Args:
        prompt: 提示文本
        default_ratio: 默认比例

    Returns:
        tuple: (清理后的提示文本, 图片数量, 比例)
    """
    # 默认值
    n = 1
    aspect_ratio = default_ratio

    # 解析n参数
    n_match = re.search(r"{n:(\d+)}", prompt)
    if n_match:
        n = int(n_match.group(1))
        if n < 1 or n > 4:
            raise ValueError(f"Invalid n value: {n}. Must be between 1 and 4.")
        prompt = prompt.replace(n_match.group(0), "").strip()

    # 解析ratio参数
    ratio_match = re.search(r"{ratio:(\d+:\d+)}", prompt)
    if ratio_match:
        aspect_ratio = ratio_match.group(1)
        if aspect_ratio not in VALID_IMAGE_RATIOS:
            raise ValueError(
                f"Invalid ratio: {aspect_ratio}. Must be one of: {', '.join(VALID_IMAGE_RATIOS)}"
            )
        prompt = prompt.replace(ratio_match.group(0), "").strip()

    return prompt, n, aspect_ratio


def extract_image_urls_from_markdown(text: str) -> List[str]:
    """
    从Markdown文本中提取图片URL

    Args:
        text: Markdown文本

    Returns:
        List[str]: 图片URL列表
    """
    pattern = IMAGE_URL_PATTERN
    matches = re.findall(pattern, text)
    return [match[1] for match in matches]


def is_valid_api_key(key: str) -> bool:
    """
    检查API密钥格式是否有效

    Args:
        key: API密钥

    Returns:
        bool: 如果密钥格式有效则返回True
    """
    # 检查Gemini API密钥格式
    if key.startswith("AIza"):
        return len(key) >= 30

    # 检查OpenAI API密钥格式
    if key.startswith("sk-"):
        return len(key) >= 30

    return False


def extract_total_token_count_from_gemini_response(
    response_body: Optional[bytes] = None,
    response_dict: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """
    Extract totalTokenCount from Gemini API response.

    Args:
        response_body: Raw response bytes (JSON), or
        response_dict: Parsed response dict (e.g. from generateContent or countTokens)

    Returns:
        totalTokenCount if found, else None
    """
    data = None
    if response_dict is not None:
        data = response_dict
    elif response_body:
        try:
            data = json.loads(response_body.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    if not data or not isinstance(data, dict):
        return None
    # usageMetadata (generateContent) or totalTokens (countTokens)
    usage = data.get("usageMetadata") or data.get("usage_metadata")
    if usage and isinstance(usage, dict):
        count = usage.get("totalTokenCount") or usage.get("total_token_count")
        if count is not None:
            return int(count)
    count = data.get("totalTokens") or data.get("total_tokens")
    if count is not None:
        return int(count)
    return None


def redact_key_for_logging(key: Any) -> str:
    """
    Redact API keys for secure logging.

    Return values are intentionally explicit for edge cases (used by tests):
    - None/empty -> "[INVALID_KEY]"
    - non-str input -> "[INVALID_KEY_TYPE]"
    - very short keys (< 12 chars) -> "[SHORT_KEY]"
    - otherwise -> "first6...last6"
    """
    if key is None or key == "":
        return "[INVALID_KEY]"
    if not isinstance(key, str):
        return "[INVALID_KEY]"
    if len(key) <= 12:
        return "[SHORT_KEY]"
    return f"{key[:6]}...{key[-6:]}"


def get_current_version(default_version: str = "0.0.0") -> str:
    """Reads the current version from the VERSION file."""
    version_file = VERSION_FILE_PATH
    try:
        with version_file.open("r", encoding="utf-8") as f:
            version = f.read().strip()
        if not version:
            helper_logger.warning(
                f"VERSION file ('{version_file}') is empty. Using default version '{default_version}'."
            )
            return default_version
        return version
    except FileNotFoundError:
        helper_logger.warning(
            f"VERSION file not found at '{version_file}'. Using default version '{default_version}'."
        )
        return default_version
    except IOError as e:
        helper_logger.error(
            f"Error reading VERSION file ('{version_file}'): {e}. Using default version '{default_version}'."
        )
        return default_version


