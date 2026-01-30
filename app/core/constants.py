"""
常量定义模块
"""

# API相关常量
API_VERSION = "v1beta"
DEFAULT_TIMEOUT = 300  # 秒
MAX_RETRIES = 3  # 最大重试次数

# 模型相关常量
SUPPORTED_ROLES = ["user", "model", "system"]
DEFAULT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TOP_P = 0.9
DEFAULT_TOP_K = 40

# 图像生成相关常量
VALID_IMAGE_RATIOS = ["1:1", "3:4", "4:3", "9:16", "16:9"]

# 本地文件上传 (deferred analyse)
DEFAULT_LOCAL_UPLOAD_DIR = "data/local_uploads"
DEFAULT_LOCAL_FILE_EXPIRE_MINUTES = 60

# 正则表达式模式
IMAGE_URL_PATTERN = r"!\[(.*?)\]\((.*?)\)"
DATA_URL_PATTERN = r"data:([^;]+);base64,(.+)"

# Audio/Video Settings
SUPPORTED_AUDIO_FORMATS = ["wav", "mp3", "flac", "ogg"]
SUPPORTED_VIDEO_FORMATS = ["mp4", "mov", "avi", "webm"]
MAX_AUDIO_SIZE_BYTES = 50 * 1024 * 1024  # Example: 50MB limit for Base64 payload
MAX_VIDEO_SIZE_BYTES = 200 * 1024 * 1024  # Example: 200MB limit

# Optional: Define MIME type mappings if needed, or handle directly in converter
AUDIO_FORMAT_TO_MIMETYPE = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
}

VIDEO_FORMAT_TO_MIMETYPE = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "webm": "video/webm",
}

GEMINI_2_FLASH_EXP_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "OFF"},
]

DEFAULT_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
]

TTS_VOICE_NAMES = [
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
]
