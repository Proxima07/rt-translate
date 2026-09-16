"""
/stats 聚合數字。記憶體環形統計，不落地。

★ 只有聚合數字，絕不含內容。

S1/S2 要量的:
  - ASR 往返 p50 / p95 / p99     → 決定要不要接 AORUS
  - 片段長度分布                  → 驗證切句參數
  - 切句原因統計 SOFT/HARD/MAX    → MAX 佔比高 = 影子視窗很重要

判讀:
  p95 < 1.5s     AORUS 完全不用接
  p95 1.5~3s     符合預期
  p95 > 3s       考慮接 AORUS 當第二路由

  MAX 佔比 < 5%   S5 影子視窗優先度可降低
  MAX 佔比 > 15%  S5 別跳過
"""
from collections import Counter, deque

_CAP = 2000

_asr_ms: deque[float] = deque(maxlen=_CAP)
_seg_ms: deque[float] = deque(maxlen=_CAP)
_reasons: Counter = Counter()
_counters: Counter = Counter()


def record_asr(ms: float) -> None:
    _asr_ms.append(ms)


def record_segment(duration_ms: float, reason: str) -> None:
    _seg_ms.append(duration_ms)
    _reasons[reason] += 1


def bump(name: str, n: int = 1) -> None:
    _counters[name] += n


def _pct(data: deque[float], q: float) -> float | None:
    if not data:
        return None
    s = sorted(data)
    i = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return round(s[i], 1)


def snapshot() -> dict:
    total = sum(_reasons.values()) or 1
    return {
        "asr_ms": {
            "n": len(_asr_ms),
            "p50": _pct(_asr_ms, 0.50),
            "p95": _pct(_asr_ms, 0.95),
            "p99": _pct(_asr_ms, 0.99),
        },
        "segment_ms": {
            "n": len(_seg_ms),
            "p50": _pct(_seg_ms, 0.50),
            "p95": _pct(_seg_ms, 0.95),
        },
        "cut_reason": dict(_reasons),
        "cut_reason_pct": {k: round(100 * v / total, 1)
                           for k, v in _reasons.items()},
        "counters": dict(_counters),
    }
