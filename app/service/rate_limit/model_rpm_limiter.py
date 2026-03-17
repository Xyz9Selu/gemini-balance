"""
Per-model RPM rate limiter (sliding 60-second window).

When the limit is reached, callers wait until a slot is free instead of being rejected.
"""

import asyncio
import time
from collections import deque
from typing import Dict

# Default rolling window length in seconds (RPM = requests per minute).
DEFAULT_WINDOW_SECONDS = 60


class _ModelState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.timestamps: deque[float] = deque()
        self.cooldown_until: float = 0.0


class ModelRpmLimiter:
    """Sliding-window RPM limiter per model. Thread-safe per model via asyncio locks."""

    def __init__(self, window_seconds: float = DEFAULT_WINDOW_SECONDS) -> None:
        self._window_seconds = window_seconds
        self._locks_lock = asyncio.Lock()
        self._state: Dict[str, _ModelState] = {}

    async def _get_state(self, model_name: str) -> _ModelState:
        async with self._locks_lock:
            if model_name not in self._state:
                self._state[model_name] = _ModelState()
            return self._state[model_name]

    async def acquire(self, model_name: str, limit: int) -> None:
        """
        Wait until a slot is available for this model, then consume one slot.

        Uses a rolling window (default 60 seconds): at most `limit` requests per window per model.
        If limit <= 0, returns immediately without waiting.
        """
        if limit <= 0:
            return
        state = await self._get_state(model_name)
        async with state.lock:
            now = time.monotonic()
            window = self._window_seconds

            # If a 429 was seen recently for this model, apply a cooldown.
            if state.cooldown_until > now:
                await asyncio.sleep(state.cooldown_until - now)
                now = time.monotonic()

            # Remove timestamps outside the window
            while state.timestamps and state.timestamps[0] < now - window:
                state.timestamps.popleft()
            # Wait until we have a free slot
            while len(state.timestamps) >= limit:
                oldest = state.timestamps[0]
                sleep_seconds = (oldest + window) - now
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
                now = time.monotonic()

                if state.cooldown_until > now:
                    await asyncio.sleep(state.cooldown_until - now)
                    now = time.monotonic()

                while state.timestamps and state.timestamps[0] < now - window:
                    state.timestamps.popleft()
            state.timestamps.append(now)

    async def trigger_cooldown(self, model_name: str, seconds: float = 60.0) -> None:
        """
        Put the given model into a cooldown period. Callers acquiring during this
        window will wait until it expires.
        """
        if seconds <= 0:
            return
        state = await self._get_state(model_name)
        async with state.lock:
            until = time.monotonic() + seconds
            if until > state.cooldown_until:
                state.cooldown_until = until


# Singleton used by the proxy (60-second window).
model_rpm_limiter = ModelRpmLimiter()
