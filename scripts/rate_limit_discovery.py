#!/usr/bin/env python3
"""
Discover from current request records (running server DB) whether 429s are explained
by the key meeting its known free-tier rate limit (RPM/RPD/TPM), or whether the key
does NOT meet that limit but 429 still occurs (suggesting an unknown rate limit).

Run from project root with the app's environment (so DB and config are available), e.g.:
  cd /path/to/gemini-balance-xyz && PYTHONPATH=. .venv/bin/python3 scripts/rate_limit_discovery.py
  # Or on the server where the app runs (same env as the running process):
  PYTHONPATH=. python3 scripts/rate_limit_discovery.py [HOURS]

Optional: HOURS = period to analyze (default 168 = 7 days).
Uses the same database and quota-cycle config as the app (QUOTA_RESET_HOUR, TIMEZONE).
"""

import asyncio
import datetime
import os
import sys
from collections import defaultdict

# Project root and load .env before importing app (so Settings can read it)
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

from app.database.connection import database, DATABASE_URL
from app.database.models import RequestLog
from app.service.stats.stats_service import get_quota_cycle_start_time
from sqlalchemy import select

# AI Studio free tier limits by model: (RPM, RPD, TPM). Substring match on model name.
FREE_TIER_LIMITS = {
    "2.5-pro": (5, 100, 250_000),
    "2.5 flash": (10, 250, 250_000),
    "2.5-flash": (10, 250, 250_000),
    "2.5 flash-lite": (15, 1_000, 250_000),
    "2.5-flash-lite": (15, 1_000, 250_000),
    "3-pro": (10, 100, 250_000),
    "2.0-flash": (5, 250, 250_000),
}
DEFAULT_LIMITS = (5, 100, 250_000)


def get_limits_for_model(model_name: str | None) -> tuple[int, int, int]:
    if not model_name or not model_name.strip():
        return DEFAULT_LIMITS
    key = (model_name or "").strip().lower()
    # Match longer patterns first so e.g. 2.5-flash-lite gets 1000 RPD, not 250
    for pattern, limits in sorted(FREE_TIER_LIMITS.items(), key=lambda x: -len(x[0])):
        if pattern in key:
            return limits
    return DEFAULT_LIMITS


def mask_key(key: str | None) -> str:
    if not key or len(key) < 8:
        return key or "-"
    return f"{key[:4]}...{key[-4:]}"


async def main() -> None:
    period_hours = 24 * 7  # default 7 days to capture RPD and 429 patterns
    if len(sys.argv) > 1:
        try:
            period_hours = int(sys.argv[1])
        except ValueError:
            pass
    now = datetime.datetime.now()
    start_time = now - datetime.timedelta(hours=period_hours)
    cycle_start = get_quota_cycle_start_time()
    cycle_start_naive = datetime.datetime.fromtimestamp(cycle_start.timestamp())

    print("Rate limit discovery (from current request records)")
    print("=" * 60)
    print(f"DB: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
    print(f"Period: last {period_hours}h (since {start_time.isoformat()})")
    print(f"Quota cycle start (RPD): {cycle_start_naive.isoformat()}")
    print()

    await database.connect()
    try:
        # Include all requests (success and failed); failed requests still consume quota and count toward RPM/RPD
        query = (
            select(
                RequestLog.api_key,
                RequestLog.model_name,
                RequestLog.request_time,
                RequestLog.total_token_count,
                RequestLog.status_code,
            )
            .where(
                RequestLog.request_time >= start_time,
                RequestLog.api_key.isnot(None),
            )
            .order_by(RequestLog.request_time.asc())
        )
        rows = await database.fetch_all(query)
    finally:
        await database.disconnect()

    if not rows:
        print("No request records in the period. Cannot determine rate limit cause.")
        return

    # Success vs failed (by status_code: 2xx = success, else = failed)
    success_count = sum(
        1 for r in rows
        if r["status_code"] is not None and 200 <= r["status_code"] < 300
    )
    failed_count = len(rows) - success_count
    print(f"Total requests: {len(rows)}  |  Success (2xx): {success_count}  |  Failed: {failed_count}")
    print()

    # Overall peak RPM (all keys and models combined) and when it occurred
    global_minute_counts: dict[tuple[int, ...], int] = defaultdict(int)
    for r in rows:
        t = r["request_time"]
        bucket = (t.year, t.month, t.day, t.hour, t.minute)
        global_minute_counts[bucket] += 1
    overall_peak_rpm = max(global_minute_counts.values()) if global_minute_counts else 0
    peak_minutes = [b for b, c in global_minute_counts.items() if c == overall_peak_rpm]
    print(f"Overall peak RPM (all keys, all models): {overall_peak_rpm}")
    if peak_minutes:
        for b in sorted(peak_minutes)[:5]:
            print(f"  Peak minute: {b[0]}-{b[1]:02d}-{b[2]:02d} {b[3]:02d}:{b[4]:02d}")
        if len(peak_minutes) > 5:
            print(f"  ... and {len(peak_minutes) - 5} other minute(s) with same count")
        # Success vs failed in the peak minute(s)
        peak_buckets_set = set(peak_minutes)
        peak_rows = [
            r for r in rows
            if (r["request_time"].year, r["request_time"].month, r["request_time"].day,
                r["request_time"].hour, r["request_time"].minute) in peak_buckets_set
        ]
        peak_success = sum(
            1 for r in peak_rows
            if r["status_code"] is not None and 200 <= r["status_code"] < 300
        )
        peak_failed = len(peak_rows) - peak_success
        print(f"  At peak minute(s): Success (2xx): {peak_success}, Failed: {peak_failed}")
    print()

    # Minutes that contain at least one 429: success vs failed in those minutes
    minute_has_429: set[tuple[int, ...]] = set()
    for r in rows:
        if r["status_code"] == 429:
            t = r["request_time"]
            minute_has_429.add((t.year, t.month, t.day, t.hour, t.minute))
    if minute_has_429:
        rows_in_429_minutes = [
            r for r in rows
            if (r["request_time"].year, r["request_time"].month, r["request_time"].day,
                r["request_time"].hour, r["request_time"].minute) in minute_has_429
        ]
        success_in_429_min = sum(
            1 for r in rows_in_429_minutes
            if r["status_code"] is not None and 200 <= r["status_code"] < 300
        )
        failed_in_429_min = len(rows_in_429_minutes) - success_in_429_min
        print(f"Minutes with ≥1 × 429: {len(minute_has_429)} minute(s)")
        print(f"  Across those minutes: Total: {len(rows_in_429_minutes)}, Success (2xx): {success_in_429_min}, Failed: {failed_in_429_min}")
        # Per-minute breakdown (up to 20 minutes)
        per_minute = []
        for b in sorted(minute_has_429):
            min_rows = [
                r for r in rows
                if (r["request_time"].year, r["request_time"].month, r["request_time"].day,
                    r["request_time"].hour, r["request_time"].minute) == b
            ]
            s = sum(1 for r in min_rows if r["status_code"] is not None and 200 <= r["status_code"] < 300)
            f = len(min_rows) - s
            c429 = sum(1 for r in min_rows if r["status_code"] == 429)
            per_minute.append((b, len(min_rows), s, f, c429))
        for b, total, s, f, c429 in per_minute[:20]:
            print(f"    {b[0]}-{b[1]:02d}-{b[2]:02d} {b[3]:02d}:{b[4]:02d}  total={total}  success={s}  failed={f}  429={c429}")
        if len(per_minute) > 20:
            print(f"    ... and {len(per_minute) - 20} more minute(s)")
    else:
        print("Minutes with ≥1 × 429: 0 (no 429 in period)")
    print()

    # Group by (key, model)
    by_key_model: dict[str, dict[str, list[tuple[datetime.datetime, int | None, int | None]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in rows:
        key = r["api_key"] or ""
        model = (r["model_name"] or "").strip() or "(unknown)"
        by_key_model[key][model].append(
            (r["request_time"], r["total_token_count"], r["status_code"])
        )

    # Compute observed vs limit per (key, model)
    results: list[dict] = []
    for key, models in by_key_model.items():
        for model, events in models.items():
            if not events:
                continue
            minute_counts: dict[tuple[int, ...], int] = defaultdict(int)
            minute_tokens: dict[tuple[int, ...], int] = defaultdict(int)
            for req_time, token_count, _ in events:
                bucket = (req_time.year, req_time.month, req_time.day, req_time.hour, req_time.minute)
                minute_counts[bucket] += 1
                if token_count is not None:
                    minute_tokens[bucket] += token_count
            observed_rpm = max(minute_counts.values()) if minute_counts else 0
            observed_tpm = max(minute_tokens.values()) if minute_tokens else None
            observed_rpd = sum(1 for req_time, _, _ in events if req_time >= cycle_start_naive)
            count_429 = sum(1 for _, _, sc in events if sc == 429)
            limit_rpm, limit_rpd, limit_tpm = get_limits_for_model(model)
            rpm_exceeded = observed_rpm > limit_rpm
            rpd_exceeded = observed_rpd > limit_rpd
            tpm_exceeded = observed_tpm is not None and observed_tpm > limit_tpm
            results.append({
                "api_key": key,
                "model_name": model,
                "observed_rpm": observed_rpm,
                "observed_rpd": observed_rpd,
                "observed_tpm": observed_tpm,
                "limit_rpm": limit_rpm,
                "limit_rpd": limit_rpd,
                "limit_tpm": limit_tpm,
                "rpm_exceeded": rpm_exceeded,
                "rpd_exceeded": rpd_exceeded,
                "tpm_exceeded": tpm_exceeded,
                "count_429": count_429,
                "request_count": len(events),
            })

    results.sort(key=lambda x: (-x["count_429"], -x["request_count"]))

    # Print table
    print(f"{'Key':<14} {'Model':<28} {'RPM':>4} {'Lim':>4} {'RPD':>5} {'Lim':>5} {'TPM':>8} {'429':>4} {'Req':>5}  Exceeded")
    print("-" * 100)
    for r in results:
        tpm_s = f"{r['observed_tpm']:,}" if r["observed_tpm"] is not None else "-"
        exc = []
        if r["rpm_exceeded"]:
            exc.append("RPM")
        if r["rpd_exceeded"]:
            exc.append("RPD")
        if r["tpm_exceeded"]:
            exc.append("TPM")
        exc_s = ",".join(exc) if exc else "-"
        print(
            f"{mask_key(r['api_key']):<14} {(r['model_name'] or '-')[:28]:<28} "
            f"{r['observed_rpm']:>4} {r['limit_rpm']:>4} {r['observed_rpd']:>5} {r['limit_rpd']:>5} "
            f"{tpm_s:>8} {r['count_429']:>4} {r['request_count']:>5}  {exc_s}"
        )

    # Verdict: did any 429 occur where known limit was NOT exceeded?
    any_429 = any(r["count_429"] > 0 for r in results)
    any_exceeded_when_429 = False
    any_429_without_exceeded = False
    for r in results:
        if r["count_429"] == 0:
            continue
        exceeded = r["rpm_exceeded"] or r["rpd_exceeded"] or r["tpm_exceeded"]
        if exceeded:
            any_exceeded_when_429 = True
        else:
            any_429_without_exceeded = True

    print()
    print("Verdict:")
    if not any_429:
        print("  No 429 responses in the period. No rate-limit conclusion.")
        return
    if any_exceeded_when_429:
        print("  The key DOES meet its known rate limit (RPM/RPD/TPM) in at least one (key, model) row where 429 occurred.")
        print("  → 429 is consistent with exceeding the documented free-tier quota.")
    if any_429_without_exceeded:
        print("  The key does NOT meet its known rate limit in at least one (key, model) row where 429 still occurred.")
        print("  → Suggests an UNKNOWN rate limit (e.g. account/project-level, or a dimension not reflected in logs).")
    if any_exceeded_when_429 and any_429_without_exceeded:
        print("  (Both cases present: some 429s align with known limits, others do not.)")


if __name__ == "__main__":
    asyncio.run(main())
