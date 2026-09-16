"""
Segmenter / ShortCutMerger 測試。

純邏輯，不需要任何音訊檔 —— 直接餵合成的機率序列。
這是整個 S1 裡唯一可以完全離線開發完成的部分。

    pytest tests/test_segmenter.py -v
"""
from typing import Iterator

import pytest

from app import config
from app.audio.segmenter import Cut, CutReason, Segmenter, ShortCutMerger

FRAME_S = config.FRAME_MS / 1000.0
VOICE = 0.9
SILENCE = 0.05


# ── 測試輔助 ────────────────────────────────────────────────

def stream(*spans: tuple[int, bool]) -> Iterator[tuple[float, float]]:
    """
    把 (毫秒, 是否有聲) 展開成音框序列。

        stream((1000, True), (900, False))
        → 1 秒語音，接 0.9 秒靜音
    """
    t = 0.0
    for ms, voiced in spans:
        for _ in range(round(ms / config.FRAME_MS)):
            yield t, (VOICE if voiced else SILENCE)
            t += FRAME_S


def run(*spans: tuple[int, bool]) -> list[Cut]:
    """跑完整段並 flush，回傳所有切點。"""
    seg = Segmenter()
    cuts = [c for t, p in stream(*spans) if (c := seg.feed(t, p))]
    if (tail := seg.flush()) is not None:
        cuts.append(tail)
    return cuts


def reasons(cuts: list[Cut]) -> list[str]:
    return [c.reason.value for c in cuts]


# ══════════════════════════════════════════════════════════════
# Segmenter
# ══════════════════════════════════════════════════════════════

def test_thinking_pause_does_not_cut():
    """
    想詞停頓（300ms）不該切。

    這是雙門檻存在的全部理由。單一門檻會把這裡切開，
    變成兩個殘缺半句，然後中文的同音字消歧就會全錯。
    """
    cuts = run(
        (1000, True),
        (300, False),   # 想詞 —— 低於 SOFT(400)
        (1000, True),
        (1000, False),  # 真句尾
    )
    assert len(cuts) == 1
    assert cuts[0].reason is CutReason.HARD
    # 整句都在裡面，沒有被中間的停頓切開
    assert cuts[0].t_start == pytest.approx(0.0, abs=FRAME_S)
    assert cuts[0].duration_ms > 2000


def test_pause_between_soft_and_hard_does_not_cut():
    """
    落在 SOFT(400) 和 HARD(800) 之間的停頓也不該切。

    SOFT 只是「開始倒數」，不是「切」。
    S5 加上 F0 訊號之後，這個區間才會依音高決定。
    """
    cuts = run(
        (1000, True),
        (600, False),   # SOFT < 600 < HARD
        (1000, True),
        (1000, False),
    )
    assert len(cuts) == 1


def test_sentence_end_cuts_with_hard_reason():
    """兩句話，中間 900ms 停頓 → 切成兩段。"""
    cuts = run(
        (1000, True),
        (900, False),
        (1000, True),
        (1000, False),
    )
    assert reasons(cuts) == ["HARD", "HARD"]
    assert cuts[0].t_end < cuts[1].t_start


def test_hangover_cancel_resets_counter():
    """
    ★ hangover 取消必須真的歸零。

    500ms 靜音 + 一小段語音 + 500ms 靜音 = 兩段各自 500ms，
    不是累積的 1000ms。沒清掉舊起點的話這裡會誤切。
    """
    cuts = run(
        (1000, True),
        (500, False),   # 未達 HARD
        (200, True),    # ★ 取消倒數
        (500, False),   # 重新起算，仍未達 HARD
        (1000, True),
        (1000, False),
    )
    assert len(cuts) == 1, "倒數沒歸零，句子被誤切了"


def test_max_segment_fuse():
    """連續講 15 秒不停 → 保險絲觸發。"""
    cuts = run((15_000, True), (1000, False))
    assert cuts[0].reason is CutReason.MAX
    assert cuts[0].duration_ms == pytest.approx(
        config.MAX_SEGMENT_MS, abs=config.FRAME_MS * 2
    )


def test_max_cut_continues_accumulating():
    """
    ★ 撞保險絲之後必須立刻接續新的一段，不能 reset 回 IDLE。

    reset 的話，第 12 秒之後的語音會全部被丟掉，
    直到下一次「從靜音轉有聲」才重新開始 —— 整段話憑空消失。
    """
    cuts = run((30_000, True), (1000, False))
    assert len(cuts) >= 3, "保險絲之後的語音被吃掉了"
    assert reasons(cuts)[:2] == ["MAX", "MAX"]
    # 時間軸連續，沒有缺口
    for a, b in zip(cuts, cuts[1:]):
        assert b.t_start == pytest.approx(a.t_end, abs=FRAME_S)


def test_hard_wins_over_max_on_same_frame():
    """
    ★ 同一個音框上 HARD 與 MAX 都成立時，判 HARD。

    11.2 秒語音 + 800ms 靜音 = 第 12.0 秒同時撞到兩個條件。
    這句話其實是好好講完的，判成 MAX 的話 S5 會白發一次
    影子視窗，而且 /stats 的 MAX 佔比虛高，誤導 S5 的取捨。
    """
    cuts = run((11_200, True), (800, False))
    assert cuts[0].reason is CutReason.HARD


def test_flush_emits_tail():
    """串流結束時還在講話 → 尾段要沖出來，不能丟。"""
    cuts = run((1000, True))
    assert len(cuts) == 1
    assert cuts[0].reason is CutReason.EOS


def test_silence_only_produces_nothing():
    """全程靜音不該生出任何片段。"""
    assert run((5000, False)) == []


def test_timestamps_exclude_padding():
    """
    時間戳是 VAD 的精確邊界，不含 padding。

    padding 是 framing.py 取音訊時才補的，
    混進時間戳的話字幕會互相重疊。
    """
    cuts = run((1000, True), (1000, False))
    assert cuts[0].t_start == pytest.approx(0.0, abs=FRAME_S)
    assert cuts[0].t_end == pytest.approx(1.0, abs=FRAME_S * 2)


# ══════════════════════════════════════════════════════════════
# ShortCutMerger
# ══════════════════════════════════════════════════════════════

def _cut(t0: float, t1: float, reason=CutReason.HARD) -> Cut:
    return Cut(t0, t1, reason)


def test_long_cuts_pass_through_immediately():
    """夠長的片段立刻吐出 —— 不增加任何延遲。"""
    m = ShortCutMerger()
    assert m.feed(_cut(0.0, 2.0)) == [_cut(0.0, 2.0)]
    assert m.feed(_cut(3.0, 5.0)) == [_cut(3.0, 5.0)]


def test_short_cut_merges_forward():
    """短片段（咳嗽、「嗯」）併入下一段。"""
    m = ShortCutMerger()
    assert m.feed(_cut(0.0, 0.3)) == []          # 300ms < MIN(500)，等
    out = m.feed(_cut(0.6, 2.6))
    assert len(out) == 1
    assert out[0].t_start == 0.0                 # 起點用短片段的
    assert out[0].t_end == 2.6


def test_short_cut_not_merged_across_large_gap():
    """
    間隔超過 MERGE_MAX_GAP_MS 就不合併。

    一個 300ms 的雜音不該跟 10 秒後的下一句黏成同一段 ——
    那會產生一個中間全是靜音的怪片段。
    """
    m = ShortCutMerger()
    m.feed(_cut(0.0, 0.3))
    out = m.feed(_cut(10.0, 12.0))
    assert len(out) == 2
    assert out[0] == _cut(0.0, 0.3)              # 自己送出去
    assert out[1] == _cut(10.0, 12.0)


def test_merged_cut_takes_later_reason():
    """合併後的片段是因後者而結束的，reason 取後者。"""
    m = ShortCutMerger()
    m.feed(_cut(0.0, 0.3, CutReason.HARD))
    out = m.feed(_cut(0.5, 2.5, CutReason.MAX))
    assert out[0].reason is CutReason.MAX


def test_merger_flush_releases_pending():
    """串流結束時卡著的短片段，就算太短也要放出去。"""
    m = ShortCutMerger()
    m.feed(_cut(0.0, 0.3))
    assert m.flush() == [_cut(0.0, 0.3)]
    assert m.flush() == []


def test_consecutive_short_cuts_accumulate():
    """連續多個短片段會一路合併，直到累積夠長才放出。"""
    m = ShortCutMerger()
    assert m.feed(_cut(0.00, 0.20)) == []        # 200ms
    assert m.feed(_cut(0.25, 0.45)) == []        # 合併後 450ms，仍 < MIN(500)
    out = m.feed(_cut(0.50, 0.90))               # 合併後 900ms > MIN
    assert len(out) == 1
    assert out[0].t_start == 0.0
    assert out[0].t_end == pytest.approx(0.90)
