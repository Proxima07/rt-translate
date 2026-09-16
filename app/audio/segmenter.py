"""
切句引擎。★ 本專案最核心的模組。

━━ 硬性約束 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
不碰 I/O、不 async、不吃音訊格式、完全決定性。

必須能被兩個地方呼叫同一份程式碼:
  線上  app/ws.py                        即時音框
  離線  tools/visualize_segmentation.py  wav 檔畫圖

理由: 你在圖上調出來的參數，必須就是線上跑的參數。
一旦兩邊走不同邏輯，視覺化工具就白做了。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

核心規則 — 雙門檻 hangover:
  進入 SOFT 後開始倒數；若在到達 HARD 之前又偵測到語音
  → 取消倒數，繼續累積。

  像汽車雨刷的間歇模式 —— 不是一有水就刷，等夠多了才動一次。

在解決什麼問題: 人講話的停頓有兩種，聲學上長得一模一樣。
  想詞 / 換氣的 300ms   ← 不該切
  真句尾的     700ms   ← 該切
單一門檻會把想詞的地方切開，變成兩個殘缺半句。

職責邊界:
  Segmenter        判斷「什麼時候切」
  ShortCutMerger   處理「太短的片段怎麼辦」（後處理，獨立可測）

  分開的理由: S1-5 調參數時，你會想分別看到「原始切點」
  和「合併後切點」的差異。混在一起就看不到了。
"""
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

from app import config


class CutReason(str, Enum):
    HARD = "HARD"          # 靜音超過 HARD_SILENCE_MS —— 正常句尾
    SOFT_PROSODY = "SOFT"  # 靜音達 SOFT 且 F0 下降（S5+，先不實作）
    MAX = "MAX"            # 撞到 MAX_SEGMENT_MS 保險絲 —— 可能切在詞中間
    EOS = "EOS"            # 串流結束時沖出來的尾段


@dataclass(frozen=True)
class Cut:
    """
    一次切句決定。

    時間戳為 VAD 的精確邊界，**不含 padding**。
    padding 是 framing.py 在取音訊時才補的，只影響送去解碼的內容。
    """
    t_start: float
    t_end: float
    reason: CutReason

    @property
    def duration_ms(self) -> float:
        return (self.t_end - self.t_start) * 1000.0


class Segmenter:
    """
    用法:

        seg = Segmenter()
        for t, prob in vad_stream:
            cut = seg.feed(t, prob)
            if cut:
                handle(cut)
        tail = seg.flush()          # 串流結束，沖出尾段
        if tail:
            handle(tail)

    feed() 除了自身狀態外沒有任何副作用，因此可直接用在離線分析。
    要求 t 單調遞增。
    """

    def __init__(self, cfg=config):
        self.cfg = cfg
        self._frame_s = cfg.FRAME_MS / 1000.0
        self.reset()

    def reset(self) -> None:
        self._speaking = False
        self._seg_start: Optional[float] = None
        self._last_voice_end: Optional[float] = None
        self._silence_started: Optional[float] = None

    # ── 對外 ────────────────────────────────────────────────

    def feed(self, t: float, speech_prob: float) -> Optional[Cut]:
        """
        餵入一個音框。

        t             該音框的**起始**時間（秒，session 起算）
        speech_prob   Silero VAD 輸出的語音機率 0~1

        回傳 Cut 表示此刻應該切；回傳 None 表示繼續累積。
        """
        t_end = t + self._frame_s
        is_voice = speech_prob >= self.cfg.VAD_THRESHOLD

        # ── IDLE：等人開口 ──
        if not self._speaking:
            if is_voice:
                self._speaking = True
                self._seg_start = t
                self._last_voice_end = t_end
                self._silence_started = None
            return None

        # ── SPEAKING ──
        if is_voice:
            self._last_voice_end = t_end
            # ★ hangover 取消：必須真的歸零，不能留著舊起點。
            #   沒清掉的話，下一次靜音會從更早的時間點開始算，
            #   靜音長度被高估，句子會提早被切開。
            self._silence_started = None
        elif self._silence_started is None:
            self._silence_started = t

        # ── 檢查切點 ──
        # ★ HARD 優先於 MAX，即使同一個音框兩者都成立。
        #   因為 reason 決定 S5 要不要發影子視窗 ——
        #   這句話其實是好好講完的，不需要修補。
        #   判錯會白花一次 ASR 呼叫，而且 /stats 的 MAX 佔比會虛高，
        #   誤導你對 S5 的取捨。
        if self._silence_started is not None:
            silence_ms = (t_end - self._silence_started) * 1000.0
            if silence_ms >= self.cfg.HARD_SILENCE_MS:
                return self._cut_and_idle(CutReason.HARD)

        seg_ms = (t_end - self._seg_start) * 1000.0
        if seg_ms >= self.cfg.MAX_SEGMENT_MS:
            return self._cut_and_continue(t_end)

        return None

    def flush(self) -> Optional[Cut]:
        """串流結束。若還有累積中的片段就沖出來。"""
        if not self._speaking or self._seg_start is None:
            return None
        cut = Cut(self._seg_start, self._last_voice_end, CutReason.EOS)
        self.reset()
        return cut

    # ── 內部 ────────────────────────────────────────────────

    def _cut_and_idle(self, reason: CutReason) -> Cut:
        """正常句尾：切完回到 IDLE，等下一次開口。"""
        cut = Cut(self._seg_start, self._last_voice_end, reason)
        self.reset()
        return cut

    def _cut_and_continue(self, t_now: float) -> Cut:
        """
        撞到保險絲：人還在講。

        ★ 不可以 reset() —— 那會把後續的語音整個丟掉，
          直到下一次「從靜音轉有聲」才重新開始累積。
          必須立刻從切點接續新的一段。
        """
        cut = Cut(self._seg_start, t_now, CutReason.MAX)
        self._seg_start = t_now
        self._last_voice_end = t_now
        self._silence_started = None
        # _speaking 維持 True
        return cut


# ══════════════════════════════════════════════════════════════
# 短片段合併（後處理）
# ══════════════════════════════════════════════════════════════

class ShortCutMerger:
    """
    小於 MIN_SEGMENT_MS 的片段不獨立成句。

    ★ 往「後」合併，不是往前。

    config.py 的註解寫「併入前一段」，但那需要把每一段都暫存等下一段，
    等於每句話都多等一整句的延遲 —— 在即時系統裡不能接受。
    往後合併只有太短的片段會等，正常句子立刻吐出。

    代價是需要一個間隔上限: 一個 300ms 的雜音不該跟 30 秒後的
    下一句話黏成同一段。超過 MERGE_MAX_GAP_MS 就讓它自己送出去。

    典型的短片段是什麼: 咳嗽、「嗯」、關門聲、VAD 誤觸發，
    或是被 MAX 切剩的尾巴。

    feed() 回傳 list 而不是單一 Cut —— 間隔過大時會同時放出
    兩個片段（暫存的那個 + 新的那個）。

    用法:

        merger = ShortCutMerger()
        for cut in raw_cuts:
            for out in merger.feed(cut):
                handle(out)
        for out in merger.flush():
            handle(out)
    """

    def __init__(self, cfg=config):
        self.cfg = cfg
        self._pending: Optional[Cut] = None

    def feed(self, cut: Cut) -> list[Cut]:
        out: list[Cut] = []

        if self._pending is not None:
            gap_ms = (cut.t_start - self._pending.t_end) * 1000.0
            if gap_ms <= self.cfg.MERGE_MAX_GAP_MS:
                # 合併。reason 取後者 —— 合併後的片段是因它而結束的。
                cut = replace(self._pending, t_end=cut.t_end, reason=cut.reason)
            else:
                # 間隔太遠，不該黏在一起。暫存的那個自己送出去。
                out.append(self._pending)
            self._pending = None

        if cut.duration_ms < self.cfg.MIN_SEGMENT_MS:
            self._pending = cut      # 太短，等下一個
        else:
            out.append(cut)          # 夠長，立刻吐 —— 不增加延遲
        return out

    def flush(self) -> list[Cut]:
        """串流結束。還卡著的短片段就算太短也要放出去。"""
        out = [self._pending] if self._pending is not None else []
        self._pending = None
        return out
