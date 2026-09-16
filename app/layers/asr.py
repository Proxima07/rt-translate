"""
ASR 層。Cut → 取音訊 → padding → wav → NCHC → Segment。

一層一檔的理由: L3 是最後才做而且可能不做，
它必須能整個不存在而系統照跑。

★ 合併流程（S2-3）在這裡收斂:
  1. 解碼完 → is_truncated() 判定
  2. 是 → 存成 pending，先推一個 rev 讓使用者看到（標記為暫定）
  3. 下一個 Cut 來 → 取「合併後的音訊範圍」重跑 ASR
  4. 用新 id 推出去，replaces 掉舊的那兩個
"""
from typing import Optional

from app import config, logging_ as log, stats
from app.audio import framing
from app.audio.segmenter import Cut
from app.layers import merge
from app.protocol import Layer, Segment
from app.providers import pool
from app.providers.base import ASRProvider
from app.session import Session


class ASRLayer:
    def __init__(self, provider: ASRProvider, cfg=config):
        self.provider = provider
        self.cfg = cfg

    async def handle_cut(self, sess: Session, cut: Cut) -> list[Segment]:
        """
        回傳要推給前端的 Segment（可能 0~2 個）。
        由 ws.py 的單一 worker 依序呼叫，所以合併邏輯是決定性的。
        """
        out: list[Segment] = []

        # ① 有 pending 表示上一段被判定切早了 → 合併重跑
        if sess.pending is not None:
            prev = sess.pending
            sess.pending = None
            combined = merge.merged_cut(prev.cut, cut)
            result = await self._decode(sess, combined)

            new_id = sess.new_seg_id()
            sess.forget(prev.seg_id)
            log.seg("merged", new=new_id, old=prev.seg_id)
            stats.bump("merged")

            out.append(Segment(
                id=new_id,
                rev=sess.next_rev(new_id),
                layer=Layer.ASR,
                t_start=combined.t_start,
                t_end=combined.t_end,
                lang=sess.source_lang,
                text=result.text,
                replaces=[prev.seg_id],
            ))
            return out

        # ② 正常路徑
        result = await self._decode(sess, cut)
        seg_id = sess.new_seg_id()

        if merge.is_truncated(result, cut, self.cfg):
            # 先讓使用者看到，但記下來等下一段合併。
            # 不先推的話，說話者停頓期間畫面會空著，感覺像壞了。
            sess.pending = merge.Pending(seg_id=seg_id, cut=cut, result=result)
            stats.bump("truncated")

        out.append(Segment(
            id=seg_id,
            rev=sess.next_rev(seg_id),
            layer=Layer.ASR,
            t_start=cut.t_start,
            t_end=cut.t_end,
            lang=sess.source_lang,
            text=result.text,
        ))
        return out

    async def flush(self, sess: Session) -> list[Segment]:
        """串流結束時，還卡著的 pending 就這樣送出去，不再等合併。"""
        sess.pending = None
        return []

    async def _decode(self, sess: Session, cut: Cut):
        pcm = framing.slice_padded(sess.ring, cut.t_start, cut.t_end, self.cfg)
        wav = framing.to_wav(pcm, self.cfg)
        result = await pool.run_asr(
            lambda: self.provider.transcribe(
                wav, sess.source_lang, sess.prompt)
        )
        stats.record_asr(result.elapsed_ms)
        stats.record_segment(cut.duration_ms, cut.reason.value)
        return result
