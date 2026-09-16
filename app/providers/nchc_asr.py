"""
NCHC ASR。

    client.audio.transcriptions.create(
        model=config.ASR_MODEL_BY_LANG[lang],
        file=wav_16k_mono,        # 已確認支援 wav
        language=lang,            # 已確認支援 —— 絕不 auto-detect
        prompt=glossary,          # 已確認支援
        response_format="verbose_json",
    )

為什麼絕不 auto-detect:
  中日共用漢字。日文被判成 zh 去解碼時，模型不報錯、不給低信心分數，
  會生出一串看起來是中文、讀起來很通順、但意思完全不對的字。
  就像拿注音輸入法去打日文 —— 不會得到亂碼，會得到像模像樣的中文。

★ 每次呼叫都記錄往返時間 → stats.py
"""
import time

from openai import AsyncOpenAI

from app import config, logging_ as log
from app.providers.base import ASRProvider, ASRResult


class NCHCASR(ASRProvider):
    def __init__(self, cfg=config):
        self.cfg = cfg
        self._client = AsyncOpenAI(
            base_url=cfg.NCHC_BASE_URL or None,
            api_key=cfg.NCHC_API_KEY or "unused",
        )

    async def transcribe(self, wav_bytes: bytes, language: str,
                         prompt: str = "") -> ASRResult:
        model = self.cfg.ASR_MODEL_BY_LANG.get(language)
        if not model:
            raise ValueError(f"沒有對應 {language} 的 ASR 模型，檢查 .env")

        t0 = time.perf_counter()
        resp = await self._client.audio.transcriptions.create(
            model=model,
            file=("audio.wav", wav_bytes, "audio/wav"),
            language=language,
            prompt=prompt or "",
            response_format="verbose_json",
        )
        elapsed = (time.perf_counter() - t0) * 1000.0

        text = (getattr(resp, "text", "") or "").strip()

        # avg_logprob 只有 verbose_json 才有，而且不是每個服務都回。
        # 拿不到就是 None —— merge.py 會退回用標點 + 時長判斷。
        avg_lp = None
        segs = getattr(resp, "segments", None)
        if segs:
            vals = [getattr(s, "avg_logprob", None) for s in segs]
            vals = [v for v in vals if v is not None]
            if vals:
                avg_lp = sum(vals) / len(vals)

        log.seg("asr_done", chars=len(text), ms=round(elapsed),
                lp=("na" if avg_lp is None else round(avg_lp, 2)))
        return ASRResult(text=text, avg_logprob=avg_lp, elapsed_ms=elapsed)
