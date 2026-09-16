"""
並行上限 + 指數退避重試。

NCHC 目前看起來沒有明文速率限制，但「沒有明文上限」通常意味著
有並行數上限，或負載高時默默變慢。這層是很便宜的保險，
可以免掉一類很難查的間歇性失敗。

優先權: L1 最高（在關鍵路徑上），L2 可排隊等待。
S2 還沒有 LLM，先把閘門建好。
"""
import asyncio
import random
from typing import Awaitable, Callable, TypeVar

from app import config, logging_ as log

T = TypeVar("T")

_asr_gate = asyncio.Semaphore(config.MAX_CONCURRENT_ASR)
_llm_gate = asyncio.Semaphore(config.MAX_CONCURRENT_LLM)


async def _run(gate: asyncio.Semaphore, fn: Callable[[], Awaitable[T]],
               what: str) -> T:
    last: Exception | None = None
    for attempt in range(config.RETRY_MAX + 1):
        async with gate:
            try:
                return await fn()
            except Exception as e:                      # noqa: BLE001
                last = e
                log.warn("provider_retry", what=what, attempt=attempt,
                         err=type(e).__name__)
        if attempt < config.RETRY_MAX:
            # 加 jitter（抖動），避免多個 session 同時重試撞在一起
            delay = config.RETRY_BASE_SECONDS * (2 ** attempt)
            await asyncio.sleep(delay * (0.5 + random.random()))
    raise last              # type: ignore[misc]


async def run_asr(fn: Callable[[], Awaitable[T]]) -> T:
    return await _run(_asr_gate, fn, "asr")


async def run_llm(fn: Callable[[], Awaitable[T]]) -> T:
    return await _run(_llm_gate, fn, "llm")
