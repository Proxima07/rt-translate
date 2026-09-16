"""
語音活動偵測。輸出 (t, speech_prob) 串流給 segmenter.py。

這個模組只負責「這個音框是不是語音」，
不做任何切句決策 —— 那是 segmenter.py 的事。

兩種引擎，介面一模一樣，用 config.VAD_ENGINE 切換:

  silero  模型判定。擋得掉鍵盤聲、關門聲、冷氣這類非語音噪音，
          講者音量忽大忽小也能自己適應。預設。

  energy  純能量門檻（氣口切）。零相依、行為完全可預測，
          在安靜房間、單一講者的場景夠用。
          缺點是任何夠大聲的東西都會被當成語音。

兩者都是有狀態的，新 session 一定要 reset()。
"""
from typing import Iterator, Protocol

import numpy as np

from app import config


class VAD(Protocol):
    def reset(self) -> None: ...
    def feed(self, pcm: np.ndarray, /) -> Iterator[tuple[float, float]]: ...


def make_vad(cfg=config) -> VAD:
    engine = getattr(cfg, "VAD_ENGINE", "silero")
    return EnergyVAD(cfg) if engine == "energy" else SileroVAD(cfg)


# ══════════════════════════════════════════════════════════════

class _Chunker:
    """把任意長度的輸入切成固定大小的音框，尾巴留到下次。"""

    def __init__(self, size: int, frame_s: float):
        self.size = size
        self.frame_s = frame_s
        self._reset_chunker()

    def _reset_chunker(self) -> None:
        self._tail = np.zeros(0, dtype=np.float32)
        self._n = 0

    def chunks(self, pcm: np.ndarray) -> Iterator[tuple[float, np.ndarray]]:
        if pcm.dtype == np.int16:
            pcm = pcm.astype(np.float32) / 32768.0
        elif pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)

        buf = np.concatenate([self._tail, pcm]) if self._tail.size else pcm
        full = len(buf) // self.size
        for i in range(full):
            yield self._n * self.frame_s, buf[i * self.size:(i + 1) * self.size]
            self._n += 1
        self._tail = buf[full * self.size:].copy()


# ══════════════════════════════════════════════════════════════

class SileroVAD(_Chunker):
    """
    Silero VAD（ONNX runtime，CPU）。
    每 32ms 音框約 0.1~0.5ms，約佔 Pi 5 一核的 2%。

    ★★ 模型要的輸入是 64 個「前文」+ 512 個新樣本 = 576，不是 512。

       這是照 Silero 自己的 OnnxWrapper.__call__ 來的:
           context_size = 64 if sr == 16000 else 32
           x = torch.cat([self._context, x], dim=1)
           self._context = x[..., -context_size:]

       而 ONNX 的輸入形狀是動態的 ['batch', 'sequence']，
       只餵 512 它不會報錯，只會安靜地算出垃圾 ——
       所有機率壓在 0.001~0.002，連真人講話都判成「不是語音」。
       實測同一段輸入，補上 context 之後輸出差 11 倍。

       這種「不報錯但算錯」的相依是最難查的，所以留這段註解。

    ★ Silero 是有狀態的 RNN: state 和 context 都要傳回去。
      新 session 一定要 reset()。
    """

    CONTEXT = 64

    def __init__(self, cfg=config):
        import onnxruntime as ort

        super().__init__(cfg.VAD_FRAME_SAMPLES, cfg.FRAME_MS / 1000.0)
        self.cfg = cfg

        opts = ort.SessionOptions()
        # Pi 5 上不要讓 ORT 自己開一堆執行緒 —— 這顆模型很小，
        # 並行的額外負擔大於收益，而且會跟 event loop 搶 CPU。
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3

        if not cfg.SILERO_MODEL_PATH.exists():
            raise FileNotFoundError(
                f"找不到 VAD 模型: {cfg.SILERO_MODEL_PATH}\n"
                f"執行: python tools/fetch_vad_model.py"
            )

        self._sess = ort.InferenceSession(
            str(cfg.SILERO_MODEL_PATH),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._sr = np.array(cfg.SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._reset_chunker()
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def feed(self, pcm: np.ndarray, /) -> Iterator[tuple[float, float]]:
        for t, frame in self.chunks(pcm):
            x = np.concatenate([self._context, frame.reshape(1, -1)], axis=1)
            out, self._state = self._sess.run(
                ["output", "stateN"],
                {"input": x, "state": self._state, "sr": self._sr},
            )
            self._context = x[:, -self.CONTEXT:]
            yield t, float(out[0][0])


# ══════════════════════════════════════════════════════════════

class EnergyVAD(_Chunker):
    """
    純能量門檻。沒有模型，行為完全可預測。

    做法是「比背景大多少」而不是「絕對音量多大」——
    絕對門檻換一支麥克風就要重調，相對門檻不用。

    背景噪音底線用非對稱追蹤:
      變安靜時跟得快（0.5 秒內），變吵時跟得很慢（幾十秒）。
      這樣講話時底線不會被自己的聲音一路抬高，
      但換了房間又能在一兩秒內重新校準。

    輸出刻意做成 0~1 的連續值而不是布林，
    這樣 segmenter 的 VAD_THRESHOLD 對兩種引擎是同一套語意。
    """

    def __init__(self, cfg=config):
        super().__init__(cfg.VAD_FRAME_SAMPLES, cfg.FRAME_MS / 1000.0)
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._reset_chunker()
        self._floor_db = -70.0
        self._primed = 0

    def feed(self, pcm: np.ndarray, /) -> Iterator[tuple[float, float]]:
        margin = getattr(self.cfg, "ENERGY_MARGIN_DB", 12.0)
        span = getattr(self.cfg, "ENERGY_SPAN_DB", 10.0)

        for t, frame in self.chunks(pcm):
            rms = float(np.sqrt(np.mean(frame * frame)))
            db = 20.0 * np.log10(max(rms, 1e-7))

            if self._primed < 15:          # 前 0.5 秒先讓底線貼上來
                self._floor_db = db if self._primed == 0 else \
                    min(self._floor_db, db)
                self._primed += 1
                yield t, 0.0
                continue

            # 非對稱追蹤：往下快、往上慢
            if db < self._floor_db:
                self._floor_db += (db - self._floor_db) * 0.15
            else:
                self._floor_db += (db - self._floor_db) * 0.0008

            over = db - self._floor_db - margin
            yield t, float(np.clip(over / span, 0.0, 1.0))
