"""
脫敏 logger。底線不是筆誤 —— 避開標準庫的 logging。

存在的唯一目的：確保逐字稿永遠不會進 log。
只記 id、字數、耗時，不記內容。

這是 S4-4 稽核裡最常失守的一點。與其事後去清，
不如從第一天就只留一個出口。

用法:
    log.seg("asr_done", seg_id=sid, chars=len(text), ms=elapsed)

禁止:
    log.info(f"辨識結果: {text}")     ← 不要這樣做
"""
import logging
import sys

from app import config

_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

_logger = logging.getLogger("rt")
_logger.setLevel(config.LOG_LEVEL)
_logger.addHandler(_h)
_logger.propagate = False


def _kv(**fields) -> str:
    return " ".join(f"{k}={v}" for k, v in fields.items())


def seg(event: str, **fields):
    """句子層級事件。fields 只接受 id / 數字 / 列舉，不接受內容。"""
    _logger.info("%s %s", event, _kv(**fields))


def info(event: str, **fields):
    _logger.info("%s %s", event, _kv(**fields))


def warn(event: str, **fields):
    _logger.warning("%s %s", event, _kv(**fields))


def error(event: str, **fields):
    # 注意：不要在這裡無腦開 exc_info=True ——
    # 堆疊可能把音訊或文字吐出來。要開之前先確認。
    _logger.error("%s %s", event, _kv(**fields))
