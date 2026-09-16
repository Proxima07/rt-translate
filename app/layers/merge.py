"""
切早了的判定與合併（S2-3）。

VAD 只聽得到「有沒有聲音」，聽不出「話講完了沒」。
所以有時會在句子中間切一刀，留下一個沒有動詞的碎片。

判定靠兩個訊號，都是解碼的免費副產品:
  結尾標點       Whisper 帶標點訓練，產出「。？！」是句子完整的強訊號
  avg_logprob    切在句中會導致殘缺片段，這個值明顯偏低

avg_logprob 不是每個服務都回。拿不到的話退回「時長太短 + 無結尾標點」，
比較粗糙但零成本，實務上抓得到大部分誤切。

★ 合併是「重新解碼」，不是「把兩段文字接起來」。
  文字接起來的話，兩段各自的邊界錯字都會留著，
  而且中間那個被切斷的字永遠救不回來。
  必須拿合併後的**音訊**重跑一次 ASR。
"""
from dataclasses import dataclass

from app import config
from app.audio.segmenter import Cut
from app.providers.base import ASRResult


@dataclass
class Pending:
    """被判定為切早、正在等下一段來合併的片段。"""
    seg_id: str
    cut: Cut
    result: ASRResult


def is_truncated(result: ASRResult, cut: Cut, cfg=config) -> bool:
    text = (result.text or "").rstrip()
    if not text:
        return False                       # 空的就是空的，合併也救不了

    has_terminal = text[-1] in cfg.TERMINAL_PUNCT
    if has_terminal:
        return False

    too_short = (cut.t_end - cut.t_start) < cfg.TRUNCATE_SECONDS
    if result.avg_logprob is None:
        return too_short                   # 降級路徑
    return too_short or result.avg_logprob < cfg.TRUNCATE_LOGPROB


def merged_cut(a: Cut, b: Cut) -> Cut:
    """把兩個 Cut 併成一個，時間範圍取聯集。"""
    return Cut(t_start=a.t_start, t_end=b.t_end, reason=b.reason)
