"""
所有可調參數集中在這裡。

不要散落在各模組，也不要放進 .env —
這些值需要跟程式碼一起版控，你會需要回頭看上次調成多少。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 放在這裡而不是靠 uvicorn --env-file ——
# tools/ 底下的腳本和 pytest 都不經過 uvicorn，一樣要讀得到設定。
load_dotenv()

# ── 切句 ────────────────────────────────────────────
VAD_THRESHOLD = 0.5       # Silero 輸出機率門檻；環境吵 → 0.6
SOFT_SILENCE_MS = 200     # 可能講完了，開始倒數，先不動作
HARD_SILENCE_MS = 500     # 確定講完了，切；語速慢的講者 → 1000
MAX_SEGMENT_MS = 16_000   # 保險絲；觸發時 S5 會額外發影子視窗
MIN_SEGMENT_MS = 200      # 太短不獨立成句，併入前一段

# 邊界緩衝：VAD 貼著發聲切，會削掉字首塞音與字尾氣音。
# 忘了做的症狀是每句頭尾固定出錯，而且你聽音檔聽不出問題。
# 只影響送去解碼的音訊，不影響 segment 的時間戳。
PAD_BEFORE_MS = 200
PAD_AFTER_MS = 300

# ── 切早了的判定（S2） ──────────────────────────────
TRUNCATE_LOGPROB = -0.9   # 起手值，務必用 S1 的實際資料校準
TRUNCATE_SECONDS = 1.5
TERMINAL_PUNCT = "。．？！?!."

# ── 觸發間隔（S3 / S5） ────────────────────────────
L2_EVERY = 3              # 句；被限流時 → 5
L3_EVERY = 20             # 句；被限流時 → 30

# ── 並行與重試 ──────────────────────────────────────
MAX_CONCURRENT_ASR = 2
MAX_CONCURRENT_LLM = 3
RETRY_MAX = 2             # 指數退避
RETRY_BASE_SECONDS = 0.5

# ── 連線 ────────────────────────────────────────────
HEARTBEAT_INTERVAL_S = 30
HEARTBEAT_TIMEOUT_S = 90  # Cloudflare 約 100 秒斷閒置 WebSocket
RING_BUFFER_SECONDS = 25  # 影子視窗需要（S5）；S1 就先備好

# ── 音訊 ────────────────────────────────────────────
SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_MS = 32             # Silero VAD 的音框大小

# ── 環境 ────────────────────────────────────────────
PORT = int(os.getenv("PORT", 8091))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", 3))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

NCHC_BASE_URL = os.getenv("NCHC_BASE_URL", "")
NCHC_API_KEY = os.getenv("NCHC_API_KEY", "")
NCHC_ASR_MODEL_ZH = os.getenv("NCHC_ASR_MODEL_ZH", "")
NCHC_ASR_MODEL_MULTI = os.getenv("NCHC_ASR_MODEL_MULTI", "")
NCHC_LLM_MODEL_SMALL = os.getenv("NCHC_LLM_MODEL_SMALL", "")
NCHC_LLM_MODEL_MEDIUM = os.getenv("NCHC_LLM_MODEL_MEDIUM", "")

# 語言 → ASR 模型
ASR_MODEL_BY_LANG = {
    "zh": NCHC_ASR_MODEL_ZH,      # Breeze-ASR-25（若 NCHC 沒有 → 填 turbo）
    "en": NCHC_ASR_MODEL_MULTI,
    "ja": NCHC_ASR_MODEL_MULTI,
}

# 短片段合併（ShortCutMerger）
# 太短的片段往「後」合併，但不能跟太遠的下一句黏在一起。
# 間隔超過這個值，短片段就自己送出去。
MERGE_MAX_GAP_MS = 2_000

# ── Silero VAD ──────────────────────────────────────
# 模型檔放進 repo（約 1.26MB）。
# 不要 pip install silero-vad —— 那個套件硬性要求 torch + torchaudio。
#   python tools/fetch_vad_model.py    # 取得模型檔
SILERO_MODEL_PATH = Path(__file__).parent / "audio" / "models" / "silero_vad_16k_op15.onnx"

# Silero 在 16kHz 下的 chunk 必須是 512 sample = 32ms，
# 剛好等於 FRAME_MS。改 FRAME_MS 會讓 VAD 失效。
VAD_FRAME_SAMPLES = 512

# ── VAD 引擎 ────────────────────────────────────────
#   "silero"  模型判定。擋得掉鍵盤聲、關門聲、冷氣。預設。
#   "energy"  純能量門檻（氣口切）。零相依、行為可預測，
#             安靜房間 + 單一講者夠用；但任何夠大聲的東西都算語音。
VAD_ENGINE = os.getenv("VAD_ENGINE", "silero")

# EnergyVAD 專用：要比背景噪音大幾 dB 才算語音
ENERGY_MARGIN_DB = 12.0
ENERGY_SPAN_DB = 10.0
