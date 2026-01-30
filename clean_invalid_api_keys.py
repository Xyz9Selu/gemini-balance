#!/usr/bin/env python3
"""
清理无效的 API Keys
检测并移除占位符、空值、格式不正确的 API keys
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from app.config.config import settings
from app.database.connection import database
from app.database.models import Settings as SettingsModel
from sqlalchemy import select, update


def is_valid_api_key(key: str) -> bool:
    """检查 API key 是否有效"""
    if not key or not isinstance(key, str):
        return False

    key = key.strip()

    # 检查是否为占位符文本
    placeholder_keywords = [
        "请在此处输入",
        "请输入",
        "API 密钥",
        "api key",
        "placeholder",
        "example",
        "your-api-key",
        "填写",
        "xxx",
        "待补充",
    ]

    for keyword in placeholder_keywords:
        if keyword.lower() in key.lower():
            return False

    # Google API key 应该以 AIza 开头
    if not key.startswith("AIza"):
        return False

    # 长度检查（Google API keys 通常是 39 个字符）
    if len(key) < 30 or len(key) > 50:
        return False

    return True


async def clean_invalid_api_keys():
    """清理数据库中的无效 API keys"""
    print("=" * 60)
    print("清理无效的 API Keys")
    print("=" * 60)

    # 连接数据库
    if not database.is_connected:
        await database.connect()
        print("✓ 已连接到数据库\n")

    # 获取当前的 API_KEYS
    query = select(SettingsModel.value).where(SettingsModel.key == "API_KEYS")
    result = await database.fetch_one(query)

    if not result:
        print("❌ 未找到 API_KEYS 配置")
        return

    try:
        api_keys = json.loads(result["value"])
    except json.JSONDecodeError:
        print(f"❌ 无法解析 API_KEYS: {result['value']}")
        return

    print(f"✓ 当前有 {len(api_keys)} 个 API keys\n")

    # 分类 API keys
    valid_keys = []
    invalid_keys = []

    for i, key in enumerate(api_keys, 1):
        if is_valid_api_key(key):
            valid_keys.append(key)
            print(f"  [{i}] ✅ 有效: {key[:15]}...")
        else:
            invalid_keys.append(key)
            # 显示完整的无效 key（如果太长则截断）
            display_key = key if len(key) < 50 else f"{key[:47]}..."
            print(f"  [{i}] ❌ 无效: {display_key}")

    print(f"\n📊 统计:")
    print(f"   ✅ 有效 keys: {len(valid_keys)}")
    print(f"   ❌ 无效 keys: {len(invalid_keys)}")

    if not invalid_keys:
        print("\n✅ 所有 API keys 都有效，无需清理")
        return

    if not valid_keys:
        print("\n⚠️  警告: 没有发现任何有效的 API keys!")
        print("   请在管理界面手动添加有效的 Google API keys")
        return

    # 询问用户确认
    print(f"\n是否将无效的 {len(invalid_keys)} 个 API keys 从数据库中移除?")
    print("(输入 'yes' 确认)")
    response = input("> ").strip().lower()

    if response != "yes":
        print("❌ 已取消")
        return

    # 更新数据库
    try:
        new_value = json.dumps(valid_keys, ensure_ascii=False)
        update_query = (
            update(SettingsModel)
            .where(SettingsModel.key == "API_KEYS")
            .values(value=new_value)
        )
        await database.execute(update_query)

        print(f"\n✅ 已更新数据库")
        print(f"   保留了 {len(valid_keys)} 个有效的 API keys")
        print(f"   移除了 {len(invalid_keys)} 个无效的 API keys")
        print("\n⚠️  请重启服务使更改生效:")
        print("   docker compose restart")

    except Exception as e:
        print(f"\n❌ 更新失败: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(clean_invalid_api_keys())
    except KeyboardInterrupt:
        print("\n\n❌ 操作已取消")
        sys.exit(1)
