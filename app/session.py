"""
Session 生命週期。

★ 零保存的關鍵：斷線時所有狀態必須確實釋放。
  S4-4 稽核會驗這一點（講 30 分鐘後斷線，觀察 RSS 回落）。

一個 Session 擁有:
  ring buffer   音訊唯一存在的地方（25 秒）
  VAD           有狀態的 RNN，不可跨 session 沿用
  Segmenter     切句狀態機
  ShortCutMerger
  rev 表        每個 segment 被更新了幾次
  pending       等待合併的片段（S2-3）
"""
import uuid
from typing import Optional

import numpy as np

from app import config
from app.audio.ring_buffer import RingBuffer
from app.audio.segmenter import Segmenter, ShortCutMerger
from app.audio.vad import make_vad
from app.layers.merge import Pending


class Session:
    def __init__(self, source_lang: str, target_lang: str,
                 glossary: list[str] | None = None, cfg=config):
        self.id = uuid.uuid4().hex[:12]
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.glossary = glossary or []

        self.ring = RingBuffer(cfg)
        self.vad = make_vad(cfg)
        self.segmenter = Segmenter(cfg)
        self.shortcuts = ShortCutMerger(cfg)

        self._revs: dict[str, int] = {}
        self.pending: Optional[Pending] = None
        self._speaking = False

        # 觀測用。純計數與機率，不含任何內容。
        self.cuts = 0
        self._frames = 0
        self._voiced = 0
        self._peak = 0.0        # VAD 機率的峰值
        self._rms = 0.0         # 原始訊號振幅的峰值
        self._reported = 0

    # ── id / rev ────────────────────────────────────────────

    def new_seg_id(self) -> str:
        return "seg_" + uuid.uuid4().hex[:8]

    def next_rev(self, seg_id: str) -> int:
        """
        rev 單調遞增。前端收到比現有更舊的 rev 直接丟棄。

        沒有這個機制的話，網路亂序會造成「字改好了又變回錯的」，
        偶發、難重現、難查。
        """
        r = self._revs.get(seg_id, 0) + 1
        self._revs[seg_id] = r
        return r

    def forget(self, seg_id: str) -> None:
        """被 replaces 掉的 segment，rev 記錄也一併清掉。"""
        self._revs.pop(seg_id, None)

    # ── 觀測 ────────────────────────────────────────────────

    def observe(self, prob: float) -> None:
        self._frames += 1
        self._peak = max(self._peak, prob)
        if prob >= config.VAD_THRESHOLD:
            self._voiced += 1

    def observe_level(self, pcm) -> None:
        """
        原始振幅。★ 這個必須跟 VAD 機率分開看 ——
        只有 VAD 機率的話，「麥克風收到一片零」和
        「有聲音但 VAD 不認為是語音」會長得一模一樣。
        """
        import numpy as np
        if pcm.size:
            self._rms = max(self._rms, float(np.abs(pcm).max()) / 32768.0)

    def heard(self) -> Optional[dict]:
        """每約 2 秒回報一次。沒到時間回 None。"""
        if self._frames - self._reported < 60:      # 60 x 32ms ≈ 1.9s
            return None
        self._reported = self._frames
        out = {
            "frames": self._frames,
            "rms": round(self._rms, 4),                 # 原始振幅 0~1
            "peak": round(self._peak, 4),               # VAD 機率
            "voiced_pct": round(100 * self._voiced / max(1, self._frames)),
            "cuts": self.cuts,
        }
        self._peak = 0.0
        self._rms = 0.0
        return out

    # ── 講話狀態（給前端游標用）───────────────────────────

    def speaking_changed(self) -> Optional[bool]:
        """回傳新狀態，沒變則 None。"""
        now = self.segmenter._speaking      # noqa: SLF001
        if now == self._speaking:
            return None
        self._speaking = now
        return now

    @property
    def prompt(self) -> str:
        """術語清單 → ASR 的 prompt 參數（約 224 token 上限）。"""
        return ", ".join(self.glossary)[:800]

    # ── 釋放 ────────────────────────────────────────────────

    def close(self) -> None:
        """
        斷線時呼叫。把大塊的東西明確斷開參照，
        不要等 GC 心情好才回收。
        """
        self.ring.reset()
        self.ring = None            # type: ignore[assignment]
        self.vad = None             # type: ignore[assignment]
        self.segmenter = None       # type: ignore[assignment]
        self.shortcuts = None       # type: ignore[assignment]
        self._revs.clear()
        self.pending = None
