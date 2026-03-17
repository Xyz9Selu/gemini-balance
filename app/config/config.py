"""
应用程序配置模块
"""

import datetime
import json
from typing import Any, Dict, List, Type, get_args, get_origin

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings
from sqlalchemy import insert, select, update

from app.core.constants import (
    API_VERSION,
    DEFAULT_LOCAL_FILE_EXPIRE_MINUTES,
    DEFAULT_LOCAL_UPLOAD_DIR,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    RETRY_SLEEP_SECONDS,
)
from app.log.logger import Logger


class Settings(BaseSettings):
    # 数据库配置
    DATABASE_TYPE: str = "mysql"  # sqlite 或 mysql
    SQLITE_DATABASE: str = "default_db"
    MYSQL_HOST: str = ""
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = ""
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = ""
    MYSQL_SOCKET: str = ""

    # 验证 MySQL 配置
    @field_validator(
        "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"
    )
    def validate_mysql_config(cls, v: Any, info: ValidationInfo) -> Any:
        if info.data.get("DATABASE_TYPE") == "mysql":
            if v is None or v == "":
                raise ValueError(
                    "MySQL configuration is required when DATABASE_TYPE is 'mysql'"
                )
        return v

    # API相关配置
    API_KEYS: List[str] = []
    ALLOWED_TOKENS: List[str] = []
    BASE_URL: str = f"https://generativelanguage.googleapis.com/{API_VERSION}"
    AUTH_TOKEN: str = ""
    MAX_FAILURES: int = 3
    TEST_MODEL: str = DEFAULT_MODEL
    TIME_OUT: int = DEFAULT_TIMEOUT
    MAX_RETRIES: int = MAX_RETRIES
    RETRY_SLEEP_SECONDS: int = RETRY_SLEEP_SECONDS
    # Per-model RPM limit (0 = disabled). When exceeded, requests wait instead of being rejected.
    MODEL_RPM_LIMIT: int = Field(default=20, ge=0, le=1000, description="Requests per minute per model; 0 = disabled")
    VERTEX_API_KEYS: List[str] = []
    VERTEX_EXPRESS_BASE_URL: str = (
        "https://aiplatform.googleapis.com/v1beta1/publishers/google"
    )

    # 自定义 Headers
    CUSTOM_HEADERS: Dict[str, str] = {}

    # 调度器配置
    CHECK_INTERVAL_HOURS: int = 1  # 默认检查间隔为1小时
    TIMEZONE: str = "Asia/Shanghai"  # 默认时区

    # 配额重置时间 (Gemini API 每日配额重置时刻, 默认 16:00 UTC+8)
    QUOTA_RESET_HOUR: int = 16  # 0-23

    # 日志配置
    LOG_LEVEL: str = "INFO"
    ERROR_LOG_RECORD_REQUEST_BODY: bool = False
    AUTO_DELETE_ERROR_LOGS_ENABLED: bool = True
    AUTO_DELETE_ERROR_LOGS_DAYS: int = 7
    AUTO_DELETE_REQUEST_LOGS_ENABLED: bool = False
    AUTO_DELETE_REQUEST_LOGS_DAYS: int = 30
    REQUEST_LOG_RECORD_BODY: bool = False
    REQUEST_LOG_BODY_MAX_BYTES: int = 65535

    # Files API
    FILES_CLEANUP_ENABLED: bool = True
    FILES_CLEANUP_INTERVAL_HOURS: int = 1
    FILES_USER_ISOLATION_ENABLED: bool = True

    # Local file upload (deferred analyse): upload to local, then to Gemini on analyse
    LOCAL_UPLOAD_DIR: str = DEFAULT_LOCAL_UPLOAD_DIR
    LOCAL_FILE_EXPIRE_MINUTES: int = DEFAULT_LOCAL_FILE_EXPIRE_MINUTES

    # Admin Session Configuration
    ADMIN_SESSION_EXPIRE: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description="Admin session expiration time in seconds (5 minutes to 24 hours)",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 设置默认AUTH_TOKEN（如果未提供）
        if not self.AUTH_TOKEN and self.ALLOWED_TOKENS:
            self.AUTH_TOKEN = self.ALLOWED_TOKENS[0]


# 创建全局配置实例
settings = Settings()


def _is_valid_api_key(key: str) -> bool:
    """
    检查 API key 是否有效

    Google API key 的标准格式：
    - 以 "AIza" 开头
    - 长度恰好为 39 个字符

    Args:
        key: 要检查的 API key

    Returns:
        bool: key 是否有效
    """
    if not key or not isinstance(key, str):
        return False

    key = key.strip()

    # Google API key 的标准格式：AIza + 35个字符 = 39字符
    return key.startswith("AIza") and len(key) == 39


def _filter_valid_api_keys(api_keys: list) -> tuple[list, list]:
    """
    过滤出有效的 API keys

    Args:
        api_keys: API keys 列表

    Returns:
        tuple: (valid_keys, invalid_keys)
    """
    valid_keys = []
    invalid_keys = []

    for key in api_keys:
        if _is_valid_api_key(key):
            valid_keys.append(key)
        else:
            invalid_keys.append(key)

    return valid_keys, invalid_keys


def _parse_db_value(key: str, db_value: str, target_type: Type) -> Any:
    """尝试将数据库字符串值解析为目标 Python 类型"""
    from app.log.logger import get_config_logger

    logger = get_config_logger()
    try:
        origin_type = get_origin(target_type)
        args = get_args(target_type)

        # 处理 List 类型
        if origin_type is list:
            # 处理 List[str]
            if args and args[0] == str:
                try:
                    parsed = json.loads(db_value)
                    if isinstance(parsed, list):
                        return [str(item) for item in parsed]
                except json.JSONDecodeError:
                    return [
                        item.strip() for item in db_value.split(",") if item.strip()
                    ]
                logger.warning(
                    f"Could not parse '{db_value}' as List[str] for key '{key}', falling back to comma split or empty list."
                )
                return [item.strip() for item in db_value.split(",") if item.strip()]
            # 处理 List[Dict[str, str]]
            elif args and get_origin(args[0]) is dict:
                try:
                    parsed = json.loads(db_value)
                    if isinstance(parsed, list):
                        valid = all(
                            isinstance(item, dict)
                            and all(isinstance(k, str) for k in item.keys())
                            and all(isinstance(v, str) for v in item.values())
                            for item in parsed
                        )
                        if valid:
                            return parsed
                        else:
                            logger.warning(
                                f"Invalid structure in List[Dict[str, str]] for key '{key}'. Value: {db_value}"
                            )
                            return []
                    else:
                        logger.warning(
                            f"Parsed DB value for key '{key}' is not a list type. Value: {db_value}"
                        )
                        return []
                except json.JSONDecodeError:
                    logger.error(
                        f"Could not parse '{db_value}' as JSON for List[Dict[str, str]] for key '{key}'. Returning empty list."
                    )
                    return []
                except Exception as e:
                    logger.error(
                        f"Error parsing List[Dict[str, str]] for key '{key}': {e}. Value: {db_value}. Returning empty list."
                    )
                    return []
        # 处理 Dict 类型
        elif origin_type is dict:
            # 处理 Dict[str, str]
            if args and args == (str, str):
                parsed_dict = {}
                try:
                    parsed = json.loads(db_value)
                    if isinstance(parsed, dict):
                        parsed_dict = {str(k): str(v) for k, v in parsed.items()}
                    else:
                        logger.warning(
                            f"Parsed DB value for key '{key}' is not a dictionary type. Value: {db_value}"
                        )
                except json.JSONDecodeError:
                    logger.error(
                        f"Could not parse '{db_value}' as Dict[str, str] for key '{key}'. Returning empty dict."
                    )
                return parsed_dict
            # 处理 Dict[str, float]
            elif args and args == (str, float):
                parsed_dict = {}
                try:
                    parsed = json.loads(db_value)
                    if isinstance(parsed, dict):
                        parsed_dict = {str(k): float(v) for k, v in parsed.items()}
                    else:
                        logger.warning(
                            f"Parsed DB value for key '{key}' is not a dictionary type. Value: {db_value}"
                        )
                except (json.JSONDecodeError, ValueError, TypeError) as e1:
                    if isinstance(e1, json.JSONDecodeError) and "'" in db_value:
                        logger.warning(
                            f"Failed initial JSON parse for key '{key}'. Attempting to replace single quotes. Error: {e1}"
                        )
                        try:
                            corrected_db_value = db_value.replace("'", '"')
                            parsed = json.loads(corrected_db_value)
                            if isinstance(parsed, dict):
                                parsed_dict = {
                                    str(k): float(v) for k, v in parsed.items()
                                }
                            else:
                                logger.warning(
                                    f"Parsed DB value (after quote replacement) for key '{key}' is not a dictionary type. Value: {corrected_db_value}"
                                )
                        except (json.JSONDecodeError, ValueError, TypeError) as e2:
                            logger.error(
                                f"Could not parse '{db_value}' as Dict[str, float] for key '{key}' even after replacing quotes: {e2}. Returning empty dict."
                            )
                    else:
                        logger.error(
                            f"Could not parse '{db_value}' as Dict[str, float] for key '{key}': {e1}. Returning empty dict."
                        )
                return parsed_dict
        # 处理 bool
        elif target_type == bool:
            return db_value.lower() in ("true", "1", "yes", "on")
        # 处理 int
        elif target_type == int:
            return int(db_value)
        # 处理 float
        elif target_type == float:
            return float(db_value)
        # 默认为 str 或其他 pydantic 能直接处理的类型
        else:
            return db_value
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        logger.warning(
            f"Failed to parse db_value '{db_value}' for key '{key}' as type {target_type}: {e}. Using original string value."
        )
        return db_value  # 解析失败则返回原始字符串


async def sync_initial_settings():
    """
    应用启动时同步配置：
    1. 从数据库加载设置。
    2. 将数据库设置合并到内存 settings (数据库优先)。
    3. 将最终的内存 settings 同步回数据库。
    """
    from app.log.logger import get_config_logger

    logger = get_config_logger()
    # 延迟导入以避免循环依赖和确保数据库连接已初始化
    from app.database.connection import database
    from app.database.models import Settings as SettingsModel

    global settings
    logger.info("Starting initial settings synchronization...")

    if not database.is_connected:
        try:
            await database.connect()
            logger.info("Database connection established for initial sync.")
        except Exception as e:
            logger.error(
                f"Failed to connect to database for initial settings sync: {e}. Skipping sync."
            )
            return

    try:
        # 1. 从数据库加载设置
        db_settings_raw: List[Dict[str, Any]] = []
        try:
            query = select(SettingsModel.key, SettingsModel.value)
            results = await database.fetch_all(query)
            db_settings_raw = [
                {"key": row["key"], "value": row["value"]} for row in results
            ]
            logger.info(f"Fetched {len(db_settings_raw)} settings from database.")
        except Exception as e:
            logger.error(
                f"Failed to fetch settings from database: {e}. Proceeding with environment/dotenv settings."
            )
            # 即使数据库读取失败，也要继续执行，确保基于 env/dotenv 的配置能同步到数据库

        db_settings_map: Dict[str, str] = {
            s["key"]: s["value"] for s in db_settings_raw
        }

        # 2. 将数据库设置合并到内存 settings (数据库优先)
        updated_in_memory = False

        for key, db_value in db_settings_map.items():
            if key == "DATABASE_TYPE":
                logger.debug(
                    f"Skipping update of '{key}' in memory from database. "
                    "This setting is controlled by environment/dotenv."
                )
                continue
            if hasattr(settings, key):
                target_type = Settings.__annotations__.get(key)
                if target_type:
                    try:
                        parsed_db_value = _parse_db_value(key, db_value, target_type)
                        memory_value = getattr(settings, key)

                        # 比较解析后的值和内存中的值
                        # 注意：对于列表等复杂类型，直接比较可能不够健壮，但这里简化处理
                        if parsed_db_value != memory_value:
                            # 检查类型是否匹配，以防解析函数返回了不兼容的类型
                            type_match = False
                            origin_type = get_origin(target_type)
                            if origin_type:  # It's a generic type
                                if isinstance(parsed_db_value, origin_type):
                                    type_match = True
                            # It's a non-generic type, or a specific generic we want to handle
                            elif isinstance(parsed_db_value, target_type):
                                type_match = True

                            if type_match:
                                setattr(settings, key, parsed_db_value)
                                logger.debug(
                                    f"Updated setting '{key}' in memory from database value ({target_type})."
                                )
                                updated_in_memory = True
                            else:
                                logger.warning(
                                    f"Parsed DB value type mismatch for key '{key}'. Expected {target_type}, got {type(parsed_db_value)}. Skipping update."
                                )

                    except Exception as e:
                        logger.error(
                            f"Error processing database setting for key '{key}': {e}"
                        )
            else:
                # 静默忽略数据库中存在但未在 Settings 类中定义的配置项
                pass

        # 如果内存中有更新，记录日志
        # 注意：不能在这里重新创建 settings 对象（settings = Settings(...)），
        # 因为这会创建一个新对象，破坏已经导入该对象的其他模块的引用
        # （例如 application.py 中的 `from app.config.config import settings`）
        # 我们已经通过 setattr() 直接更新了全局 settings 对象的属性，
        # 这样所有已导入 settings 的模块都能看到更新后的值
        if updated_in_memory:
            logger.info(
                "Settings object updated in-place from database values. "
                f"Updated keys: {[k for k, v in db_settings_map.items() if hasattr(settings, k)]}"
            )

        # 2.5. 清理无效的 API keys（在同步回数据库之前）
        if settings.API_KEYS:
            original_count = len(settings.API_KEYS)
            valid_keys, invalid_keys = _filter_valid_api_keys(settings.API_KEYS)

            if invalid_keys:
                settings.API_KEYS = valid_keys
                logger.warning(
                    f"Removed {len(invalid_keys)} invalid API key(s). "
                    f"Valid keys: {len(valid_keys)}/{original_count}"
                )

                if not valid_keys:
                    logger.error(
                        "All API keys are invalid! Please add valid Google API keys "
                        "through the admin interface."
                    )

        # 同样清理 VERTEX_API_KEYS
        if settings.VERTEX_API_KEYS:
            original_count = len(settings.VERTEX_API_KEYS)
            valid_keys, invalid_keys = _filter_valid_api_keys(settings.VERTEX_API_KEYS)

            if invalid_keys:
                settings.VERTEX_API_KEYS = valid_keys
                logger.warning(
                    f"Removed {len(invalid_keys)} invalid Vertex API key(s). "
                    f"Valid keys: {len(valid_keys)}/{original_count}"
                )

        # 3. 将最终的内存 settings 同步回数据库
        final_memory_settings = settings.model_dump()
        settings_to_update: List[Dict[str, Any]] = []
        settings_to_insert: List[Dict[str, Any]] = []
        now = datetime.datetime.now(datetime.timezone.utc)

        existing_db_keys = set(db_settings_map.keys())

        for key, value in final_memory_settings.items():
            if key == "DATABASE_TYPE":
                logger.debug(
                    f"Skipping synchronization of '{key}' to database. "
                    "This setting is controlled by environment/dotenv."
                )
                continue

            # 序列化值为字符串或 JSON 字符串
            if isinstance(value, (list, dict)):
                db_value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bool):
                db_value = str(value).lower()
            elif value is None:
                db_value = ""
            else:
                db_value = str(value)

            data = {
                "key": key,
                "value": db_value,
                "description": f"{key} configuration setting",
                "updated_at": now,
            }

            if key in existing_db_keys:
                # 仅当值与数据库中的不同时才更新
                if db_settings_map[key] != db_value:
                    settings_to_update.append(data)
            else:
                # 如果键不在数据库中，则插入
                data["created_at"] = now
                settings_to_insert.append(data)

        # 在事务中执行批量插入和更新
        if settings_to_insert or settings_to_update:
            try:
                async with database.transaction():
                    if settings_to_insert:
                        # 获取现有描述以避免覆盖
                        query_existing = select(
                            SettingsModel.key, SettingsModel.description
                        ).where(
                            SettingsModel.key.in_(
                                [s["key"] for s in settings_to_insert]
                            )
                        )
                        existing_desc = {
                            row["key"]: row["description"]
                            for row in await database.fetch_all(query_existing)
                        }
                        for item in settings_to_insert:
                            item["description"] = existing_desc.get(
                                item["key"], item["description"]
                            )

                        query_insert = insert(SettingsModel).values(settings_to_insert)
                        await database.execute(query=query_insert)
                        logger.info(
                            f"Synced (inserted) {len(settings_to_insert)} settings to database."
                        )

                    if settings_to_update:
                        # 获取现有描述以避免覆盖
                        query_existing = select(
                            SettingsModel.key, SettingsModel.description
                        ).where(
                            SettingsModel.key.in_(
                                [s["key"] for s in settings_to_update]
                            )
                        )
                        existing_desc = {
                            row["key"]: row["description"]
                            for row in await database.fetch_all(query_existing)
                        }

                        for setting_data in settings_to_update:
                            setting_data["description"] = existing_desc.get(
                                setting_data["key"], setting_data["description"]
                            )
                            query_update = (
                                update(SettingsModel)
                                .where(SettingsModel.key == setting_data["key"])
                                .values(
                                    value=setting_data["value"],
                                    description=setting_data["description"],
                                    updated_at=setting_data["updated_at"],
                                )
                            )
                            await database.execute(query=query_update)
                        logger.info(
                            f"Synced (updated) {len(settings_to_update)} settings to database."
                        )
            except Exception as e:
                logger.error(
                    f"Failed to sync settings to database during startup: {str(e)}"
                )
        else:
            logger.info(
                "No setting changes detected between memory and database during initial sync."
            )

        # 刷新日志等级
        Logger.update_log_levels(final_memory_settings.get("LOG_LEVEL"))

    except Exception as e:
        logger.error(f"An unexpected error occurred during initial settings sync: {e}")
    finally:
        if database.is_connected:
            try:
                pass
            except Exception as e:
                logger.error(f"Error disconnecting database after initial sync: {e}")

    logger.info("Initial settings synchronization finished.")
