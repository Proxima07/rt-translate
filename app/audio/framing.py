"""
音訊切片、padding、PCM → wav。

★ padding 是必做項:
  切出來的音訊前後各補 PAD_BEFORE_MS / PAD_AFTER_MS。
  VAD 貼著發聲切，會削掉字首塞音（ㄅㄉㄍ、p/t/k）和字尾氣音，
  模型讀到削過的邊界，前後一兩個字就會錯。

  這個 bug 很難抓 —— 你用耳朵聽切出來的音檔覺得完全正常，
  但模型不是用耳朵聽的。

  padding 只影響送去解碼的音訊，不影響 Cut 的時間戳。

送 NCHC 用 wav 不用 mp3:
  mp3 每次編碼多 50~150ms，而且 encoder 有 padding 延遲。
  wav 用標準庫 wave 就能寫，不需要任何額外套件。
"""
import io
import wave

import numpy as np

from app import config
from app.audio.ring_buffer import RingBuffer


def slice_padded(ring: RingBuffer, t_start: float, t_end: float,
                 cfg=config) -> np.ndarray:
    """依 Cut 的時間戳取音訊，前後補 padding。"""
    return ring.read(
        t_start - cfg.PAD_BEFORE_MS / 1000.0,
        t_end + cfg.PAD_AFTER_MS / 1000.0,
    )


def to_wav(pcm: np.ndarray, cfg=config) -> bytes:
    """int16 mono → wav bytes（記憶體內，不落地）。"""
    if pcm.dtype != np.int16:
        pcm = pcm.astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(cfg.CHANNELS)
        w.setsampwidth(2)          # int16
        w.setframerate(cfg.SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
