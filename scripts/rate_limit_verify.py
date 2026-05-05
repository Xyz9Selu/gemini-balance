#!/usr/bin/env python3
"""
使用数据库 t_settings 中的 API_KEYS, 结合 keys-account.txt 的账号标注,
直接请求 Google Generative Language API, 探测上游 RPM / TPM 触发的 429.

运行 (项目根目录):
  cd /path/to/gemini-balance-xyz && PYTHONPATH=. .venv/bin/python3 scripts/rate_limit_verify.py

可选参数见 --help. 仅打印 key 与账号映射、不请求 API: --dry-run

说明:
  - RPM: 在滑动 60s 窗口内统计请求次数, 记录首次 429 前窗口内请求数.
  - TPM: 在滑动 60s 窗口内累加 usageMetadata 中的 token 数 (prompt+output 等),
    使用较大输入逼近 TPM 上限 (默认每请求约数万 token, 慎用配额).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

# 项目根
_script_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_script_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)
os.chdir(_root)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from sqlalchemy import select

from app.core.constants import API_VERSION


def mask_key(k: str | None) -> str:
    if not k or len(k) < 12:
        return k or "-"
    return f"{k[:6]}...{k[-4:]}"


def parse_keys_account_file(path: Path) -> dict[str, dict[str, str]]:
    """
    keys-account.txt 行格式: key11: AIza...
    返回 api_key -> { "label": "key11", "account": "1" }  (account 取 label 中 key 后第一个数字位).
    """
    out: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return out
    line_re = re.compile(r"^\s*(key\d+)\s*:\s*(AIza\S+)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = line_re.match(line.strip())
        if not m:
            continue
        label, api_key = m.group(1), m.group(2).strip()
        digits = re.sub(r"\D", "", label.replace("key", "", 1))
        account = digits[0] if digits else "?"
        out[api_key] = {"label": label, "account": f"account-{account}"}
    return out


async def fetch_api_keys_from_db() -> list[str]:
    from app.database.connection import connect_to_db, database
    from app.database.models import Settings as SettingsModel

    if not database.is_connected:
        await connect_to_db()
    q = select(SettingsModel.value).where(SettingsModel.key == "API_KEYS")
    row = await database.fetch_one(q)
    if not row or not row["value"]:
        return []
    raw = row["value"]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return [x.strip() for x in raw.split(",") if x.strip()]


MINIMAL_GEN_PAYLOAD: dict[str, Any] = {
    "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
    "generationConfig": {"maxOutputTokens": 1},
}


async def find_reachable_key(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    keys: list[str],
) -> tuple[str, int] | None:
    """
    依次尝试 keys, 返回第一个可连上 Generative Language 的 (key, http_status).
    认为 HTTP 200 / 429 表示端点与 key 对该环境可用; 其它则换下一个 key.
    若全部失败返回 None, 并在 stdout 打印最后一次响应摘要.
    """
    url_tpl = f"{base_url}/models/{model}:generateContent?key={{key}}"
    last_summary = ""
    for k in keys:
        url = url_tpl.format(key=k)
        try:
            r = await client.post(url, json=MINIMAL_GEN_PAYLOAD)
        except Exception as e:
            last_summary = str(e)[:600]
            continue
        if r.status_code in (200, 429):
            return k, r.status_code
        try:
            err = r.json().get("error", {})
            msg = err.get("message", r.text[:200])
        except Exception:
            msg = r.text[:200]
        last_summary = f"HTTP {r.status_code}: {msg}"
    print(
        "错误: 数据库中的 key 均无法完成探测请求 (需要 HTTP 200 或 429). "
        "常见原因: 出口地区不支持 Google Generative Language API (FAILED_PRECONDITION), 或 key 无效."
    )
    print(f"  最后一次: {last_summary}")
    return None


def default_base_url() -> str:
    try:
        from app.config.config import settings

        if settings.BASE_URL:
            return settings.BASE_URL.rstrip("/")
    except Exception:
        pass
    return f"https://generativelanguage.googleapis.com/{API_VERSION}"


def rolling_count_60s(ts_list: list[float], now: float) -> int:
    cutoff = now - 60.0
    return sum(1 for t in ts_list if t >= cutoff)


def rolling_tokens_60s(
    records: list[tuple[float, int]], now: float
) -> int:
    cutoff = now - 60.0
    return sum(tok for t, tok in records if t >= cutoff)


@dataclass
class RpmResult:
    key_mask: str
    label: str
    account: str
    total_requests: int
    http_429_count: int
    first_429_at_request: int | None
    rolling_req_at_first_429: int | None
    sample_error: str | None


async def probe_rpm_single_key(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    api_key: str,
    meta: dict[str, str],
    max_requests: int,
    pause_sec: float,
) -> RpmResult:
    url = f"{base_url}/models/{model}:generateContent?key={api_key}"
    payload = dict(MINIMAL_GEN_PAYLOAD)
    payload["contents"] = [{"role": "user", "parts": [{"text": "ok"}]}]
    ts: list[float] = []
    http_429 = 0
    first_429_idx: int | None = None
    rolling_at_429: int | None = None
    err_sample: str | None = None

    for i in range(1, max_requests + 1):
        t0 = time.monotonic()
        try:
            r = await client.post(url, json=payload)
        except Exception as e:
            err_sample = str(e)[:500]
            break
        ts.append(time.time())
        if r.status_code == 429:
            http_429 += 1
            if first_429_idx is None:
                first_429_idx = i
                rolling_at_429 = rolling_count_60s(ts, ts[-1])
            if err_sample is None:
                err_sample = r.text[:800]
            break
        if r.status_code != 200:
            err_sample = f"HTTP {r.status_code}: {r.text[:500]}"
            break
        if pause_sec > 0:
            await asyncio.sleep(pause_sec)
        # 防止事件循环饿死
        if i % 50 == 0:
            await asyncio.sleep(0)

    return RpmResult(
        key_mask=mask_key(api_key),
        label=meta.get("label", "?"),
        account=meta.get("account", "?"),
        total_requests=len(ts),
        http_429_count=http_429,
        first_429_at_request=first_429_idx,
        rolling_req_at_first_429=rolling_at_429,
        sample_error=err_sample,
    )


async def probe_rpm_round_robin(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    keys: list[str],
    labels: list[dict[str, str]],
    max_requests: int,
) -> None:
    url_tpl = f"{base_url}/models/{model}:generateContent?key={{key}}"
    payload = dict(MINIMAL_GEN_PAYLOAD)
    payload["contents"] = [{"role": "user", "parts": [{"text": "rr"}]}]
    ts: list[float] = []
    for i in range(max_requests):
        k = keys[i % len(keys)]
        meta = labels[i % len(labels)]
        url = url_tpl.format(key=k)
        r = await client.post(url, json=payload)
        ts.append(time.time())
        if r.status_code == 429:
            roll = rolling_count_60s(ts, ts[-1])
            print(
                f"  [round-robin] 429 at iteration {i + 1}, "
                f"keys={len(keys)}, rolling_60s_requests≈{roll}, "
                f"key={mask_key(k)} ({meta.get('label', '?')}, {meta.get('account', '?')})"
            )
            print(f"    body: {r.text[:600]}")
            return
        if r.status_code != 200:
            print(f"  [round-robin] HTTP {r.status_code} at {i + 1}: {r.text[:400]}")
            return
    print(f"  [round-robin] no 429 in {max_requests} requests.")


async def probe_tpm_single_key(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    api_key: str,
    meta: dict[str, str],
    approx_tokens_per_request: int,
    max_requests: int,
) -> None:
    """
    使用重复文本放大 prompt token; 依赖响应中的 usageMetadata.
    """
    # 粗略: 英文约 4 字符/token, 用重复 "word " 稳定放大
    chars_per_tok = 5
    n_chars = max(200, approx_tokens_per_request * chars_per_tok)
    blob = ("word " * (n_chars // 5))[:n_chars]
    url = f"{base_url}/models/{model}:generateContent?key={api_key}"
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": blob}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }
    token_records: list[tuple[float, int]] = []
    for i in range(1, max_requests + 1):
        r = await client.post(url, json=payload)
        now = time.time()
        if r.status_code == 429:
            roll_tok = rolling_tokens_60s(token_records, now)
            print(
                f"  [TPM] 429 at request #{i}, key={mask_key(api_key)} "
                f"({meta.get('label', '?')}, {meta.get('account', '?')}), "
                f"rolling_60s_tokens≈{roll_tok}"
            )
            print(f"    body: {r.text[:800]}")
            return
        if r.status_code != 200:
            print(f"  [TPM] HTTP {r.status_code} at #{i}: {r.text[:500]}")
            return
        try:
            data = r.json()
        except json.JSONDecodeError:
            print(f"  [TPM] bad JSON at #{i}")
            return
        um = data.get("usageMetadata") or {}
        total = int(
            um.get("totalTokenCount")
            or (
                (um.get("promptTokenCount") or 0)
                + (um.get("candidatesTokenCount") or 0)
                + (um.get("cachedContentTokenCount") or 0)
            )
        )
        token_records.append((now, total))
        roll_tok = rolling_tokens_60s(token_records, now)
        if i % 5 == 0 or i == 1:
            print(
                f"  [TPM] req {i}: totalTokens={total}, rolling_60s_tokens≈{roll_tok}"
            )
    print(f"  [TPM] no 429 after {max_requests} large requests.")


async def main_async(args: argparse.Namespace) -> int:
    account_path = Path(args.keys_account).resolve()
    key_to_meta = parse_keys_account_file(account_path)

    keys = await fetch_api_keys_from_db()
    if not keys:
        print("数据库中未找到 API_KEYS 或列表为空. 请确认 t_settings 已配置.", file=sys.stderr)
        return 1

    print(f"数据库 API_KEYS 数量: {len(keys)}", flush=True)
    print(f"keys-account.txt 映射条目: {len(key_to_meta)} (路径: {account_path})", flush=True)
    base_url = args.base_url or default_base_url()
    print(f"BASE_URL: {base_url}", flush=True)
    print(f"模型: {args.model}", flush=True)

    for k in keys:
        m = key_to_meta.get(k, {"label": "(unknown)", "account": "(unknown)"})
        print(f"  {mask_key(k)}  {m['label']:>8}  {m['account']}")

    if args.dry_run:
        return 0

    labels_list = [key_to_meta.get(k, {"label": "?", "account": "?"}) for k in keys]

    timeout = httpx.Timeout(120.0, read=120.0)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        print("\n--- 探测: 寻找当前网络下可用的 key (HTTP 200 或 429) ---")
        reachable = await find_reachable_key(client, base_url, args.model, keys)
        if reachable is None:
            return 2
        probe_key, probe_status = reachable
        probe_meta = key_to_meta.get(probe_key, {"label": "?", "account": "?"})
        print(
            f"  选用 key={mask_key(probe_key)} ({probe_meta.get('label')}, {probe_meta.get('account')}), "
            f"探测请求 HTTP {probe_status}"
        )
        if probe_status == 429:
            print(
                "  提示: 探测阶段已 429, 可能配额已紧张; RPM 结果可能立刻为限流状态."
            )

        # 1) 同 key RPM
        print("\n--- 测试 A: 单 key 快速连续请求 (RPM / 429) ---")
        r = await probe_rpm_single_key(
            client,
            base_url,
            args.model,
            probe_key,
            probe_meta,
            max_requests=args.max_rpm_requests,
            pause_sec=args.rpm_pause,
        )
        print(
            f"  key={r.key_mask} ({r.label}, {r.account})\n"
            f"  总请求(成功发起次数): {r.total_requests}\n"
            f"  HTTP 429 次数: {r.http_429_count}\n"
            f"  首次 429 为第几次请求: {r.first_429_at_request}\n"
            f"  首次 429 时滑动 60s 内请求数: {r.rolling_req_at_first_429}\n"
            f"  错误样例: {r.sample_error[:400] if r.sample_error else '-'}"
        )

        # 2) 不同 key 轮询 (若库中至少 2 个 key)
        if len(keys) >= 2:
            print("\n--- 测试 B: 多 key 轮询 (是否共享项目级配额) ---")
            await probe_rpm_round_robin(
                client,
                base_url,
                args.model,
                keys[: min(8, len(keys))],
                labels_list[: min(8, len(keys))],
                max_requests=args.max_rr_requests,
            )

        # 3) 不同账号: 各取第一个属于不同 account 的 key
        by_acc: dict[str, str] = {}
        for k in keys:
            acc = key_to_meta.get(k, {}).get("account", "?")
            if acc not in by_acc:
                by_acc[acc] = k
        distinct = [(by_acc[a], key_to_meta.get(by_acc[a], {})) for a in sorted(by_acc)]
        if len(distinct) >= 2:
            print("\n--- 测试 C: 不同 account 各取 1 个 key 轮流请求 ---")
            dk = [x[0] for x in distinct[:6]]
            dl = [x[1] for x in distinct[:6]]
            await probe_rpm_round_robin(
                client, base_url, args.model, dk, dl, max_requests=args.max_rr_requests
            )

        if args.tpm:
            print("\n--- 测试 D: 单 key 大 prompt (TPM / 429) ---")
            await probe_tpm_single_key(
                client,
                base_url,
                args.model,
                probe_key,
                probe_meta,
                approx_tokens_per_request=args.tpm_tokens_per_req,
                max_requests=args.max_tpm_requests,
            )

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verify Google API RPM/TPM limits using DB keys.")
    p.add_argument(
        "--keys-account",
        default=str(Path(_root) / "keys-account.txt"),
        help="keys-account.txt 路径",
    )
    p.add_argument("--model", default="gemini-2.5-flash-lite", help="模型 id")
    p.add_argument("--base-url", default="", help="覆盖默认 Generative Language base URL")
    p.add_argument("--dry-run", action="store_true", help="只加载 key 与映射, 不请求 API")
    p.add_argument("--max-rpm-requests", type=int, default=80, help="单 key RPM 探测最大请求数")
    p.add_argument("--rpm-pause", type=float, default=0.0, help="请求间休眠秒数 (0=最快速度)")
    p.add_argument("--max-rr-requests", type=int, default=120, help="轮询探测最大请求数")
    p.add_argument("--tpm", action="store_true", help="执行 TPM 大流量探测 (消耗配额)")
    p.add_argument("--tpm-tokens-per-req", type=int, default=20000, help="每请求约目标 token 量级")
    p.add_argument("--max-tpm-requests", type=int, default=30, help="TPM 探测最多请求次数")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        rc = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        rc = 130
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
