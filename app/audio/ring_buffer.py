"""
環形緩衝區，保留最近 RING_BUFFER_SECONDS（25 秒）音訊。

S1 用途: 切片來源
S2 用途: 合併重跑時要回頭取更早的音訊
S5 用途: 影子視窗要回頭取 [start+9s, start+21s]

★ 零保存架構下，這是音訊唯一存在的地方。
  斷線即釋放，磁碟完全不碰。

驗收: 講 5 分鐘，記憶體用量持平不成長。
"""
import numpy as np

from app import config


class RingBuffer:
    """
    固定容量的 int16 環形緩衝。

    對外用「絕對時間（秒）」定位，內部自己換算成 sample index。
    超出保留範圍的請求會被夾到可用範圍，不會噴錯 ——
    因為呼叫端拿到 Cut 時音訊有可能剛好被輾過去了，
    這種情況寧可給一段短的，也不要讓整個 session 掛掉。
    """

    def __init__(self, cfg=config):
        self.sr = cfg.SAMPLE_RATE
        self.capacity = int(cfg.RING_BUFFER_SECONDS * self.sr)
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros(self.capacity, dtype=np.int16)
        self._pos = 0        # 下一個寫入位置
        self._total = 0      # 累計寫入的 sample 數（永不歸零）

    def write(self, pcm: np.ndarray) -> None:
        if pcm.dtype != np.int16:
            pcm = pcm.astype(np.int16)
        n = len(pcm)
        if n >= self.capacity:
            # 一次寫爆整個 buffer，只留最後那段
            self._buf[:] = pcm[-self.capacity:]
            self._pos = 0
            self._total += n
            return

        end = self._pos + n
        if end <= self.capacity:
            self._buf[self._pos:end] = pcm
        else:
            split = self.capacity - self._pos
            self._buf[self._pos:] = pcm[:split]
            self._buf[:end - self.capacity] = pcm[split:]
        self._pos = end % self.capacity
        self._total += n

    @property
    def now(self) -> float:
        """目前寫到的時間點（秒）。"""
        return self._total / self.sr

    @property
    def oldest(self) -> float:
        """還留得住的最早時間點（秒）。"""
        return max(0.0, (self._total - self.capacity) / self.sr)

    def read(self, t_start: float, t_end: float) -> np.ndarray:
        """取 [t_start, t_end) 的音訊。超出保留範圍的部分會被夾掉。"""
        t_start = max(t_start, self.oldest)
        t_end = min(t_end, self.now)
        if t_end <= t_start:
            return np.zeros(0, dtype=np.int16)

        i0 = int(t_start * self.sr)
        i1 = int(t_end * self.sr)
        n = i1 - i0

        # 絕對 index → 環形 index
        start = (self._pos - (self._total - i0)) % self.capacity
        end = start + n
        if end <= self.capacity:
            return self._buf[start:end].copy()
        split = self.capacity - start
        return np.concatenate([self._buf[start:], self._buf[:end - self.capacity]])
