#!/usr/bin/env python3
"""
rt-translate - S1 專案骨架產生器

用法:
    python scaffold_rt_translate.py              # 建在目前目錄
    python scaffold_rt_translate.py D:\\dev\\rt-translate
    python scaffold_rt_translate.py --dry-run    # 只列出會建什麼，不實際寫

特性:
    - 純標準函式庫，Windows / macOS / Linux 都能跑
    - 已存在的檔案一律跳過，不會覆蓋你的修改
    - 一律寫入 LF 換行（就算在 Windows 上跑也一樣）
    - 可重複執行
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

FILES: dict[str, str] = {}


def f(path: str, content: str) -> None:
    """登記一個檔案。content 前後的空行會被修掉。"""
    FILES[path] = content.strip("\n") + "\n"


# ══════════════════════════════════════════════════════════════
# 根目錄
# ══════════════════════════════════════════════════════════════

f(".gitignore", r"""
.env
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/

# PyCharm
.idea/

tests/fixtures/*.wav
tests/fixtures/*.opus
tools/out/
""")

f(".gitattributes", r"""
# Windows 開發 / Linux 部署的必要設定。
# 沒有這個檔案，Git 可能把 CRLF 提交進 repo，
# 到 Rasp 上會出現 "bad interpreter: /bin/bash^M" 之類的錯誤。
* text=auto eol=lf

*.py   text eol=lf
*.js   text eol=lf
*.sh   text eol=lf
*.yml  text eol=lf
*.md   text eol=lf
Dockerfile text eol=lf

*.wav  binary
*.opus binary
*.png  binary
""")

f(".env.example", r"""
# NCHC
NCHC_BASE_URL=
NCHC_API_KEY=
NCHC_ASR_MODEL_ZH=
NCHC_ASR_MODEL_MULTI=
NCHC_LLM_MODEL_SMALL=
NCHC_LLM_MODEL_MEDIUM=

# 服務
PORT=8091
MAX_SESSIONS=3
LOG_LEVEL=INFO

# 門檻值等參數在 app/config.py，不在這裡。
# 理由：它們要跟程式碼一起版控，你會需要回頭看上次調成多少。
""")

f("pyproject.toml", r"""
[project]
name = "rt-translate"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "websockets>=13",
    "onnxruntime>=1.19",
    "numpy>=1.26",
    "httpx>=0.27",
    "openai>=1.50",
]

[project.optional-dependencies]
# 只在開發機安裝。部署到 Rasp 時用 `pip install .`，不含這些。
dev = [
    "pytest>=8",
    "matplotlib>=3.9",   # tools/visualize_segmentation.py
    "soundfile>=0.12",   # tools/
]

[tool.pytest.ini_options]
testpaths = ["tests"]
""")

f("README.md", r"""
# rt-translate

即時語音辨識與翻譯服務。切句在本地，辨識與翻譯走 NCHC。
伺服器端零保存 — 前端是唯一的真實來源。

設計文件：`rt-translate-system-plan.md`
實作計畫：`rt-translate-implementation-plan.md`

## 開發

    python -m venv .venv
    .venv\Scripts\activate          # Windows
    pip install -e ".[dev]"
    copy .env.example .env          # 填入 NCHC 設定
    uvicorn app.main:app --reload --port 8091

## 調切句參數

    python tools/visualize_segmentation.py tests/fixtures/sample.wav

輸出一張圖到 tools/out/，含波形、VAD 機率曲線、切點與觸發原因。
**調參數時看圖，不要看數字。**

## 目前進度

- [ ] S1 骨架與切句
- [ ] S2 協定與修正
- [ ] S3 翻譯 L1 + L2
- [ ] S4 匯出與零保存收尾
- [ ] S5 L3 段落重譯（選配，S4 用滿兩週後再決定）
""")

f("Dockerfile", r"""
FROM python:3.12-slim

# 不寫 .pyc — 搭配 compose 的 read_only
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app/ ./app/
COPY web/ ./web/
COPY prompts/ ./prompts/

EXPOSE 8091
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091"]
""")

f("docker-compose.yml", r"""
services:
  rt-translate:
    build: .
    container_name: rt-translate
    restart: unless-stopped

    ports:
      - "127.0.0.1:8091:8091"

    env_file: .env

    # ── 零保存的強制手段 ───────────────────────────
    # 不是「我們沒有寫檔案」，而是「寫不進去」。
    read_only: true
    tmpfs:
      - /tmp:size=64m
    # ──────────────────────────────────────────────

    mem_limit: 1g
    cpus: 3.0

    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
""")

# ══════════════════════════════════════════════════════════════
# app/
# ══════════════════════════════════════════════════════════════

f("app/__init__.py", "")

f("app/config.py", r'''
"""
所有可調參數集中在這裡。

不要散落在各模組，也不要放進 .env —
這些值需要跟程式碼一起版控，你會需要回頭看上次調成多少。
"""
import os

# ── 切句 ────────────────────────────────────────────
VAD_THRESHOLD = 0.5       # Silero 輸出機率門檻；環境吵 → 0.6
SOFT_SILENCE_MS = 400     # 可能講完了，開始倒數，先不動作
HARD_SILENCE_MS = 800     # 確定講完了，切；語速慢的講者 → 1000
MAX_SEGMENT_MS = 12_000   # 保險絲；觸發時 S5 會額外發影子視窗
MIN_SEGMENT_MS = 500      # 太短不獨立成句，併入前一段

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
''')

f("app/logging_.py", r'''
"""
脫敏 logger。底線不是筆誤 —— 避開標準庫的 logging。

存在的唯一目的：確保逐字稿永遠不會進 log。
只記 id、字數、耗時，不記內容。

這是 S4-4 稽核裡最常失守的一點。與其事後去清，
不如從第一天就只留一個出口。

用法:
    log.seg("asr_done", seg_id=sid, chars=len(text), ms=elapsed)

禁止:
    log.info(f"辨識結果: {text}")     ← 不要這樣做
"""
import logging
import sys

from app import config

_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

_logger = logging.getLogger("rt")
_logger.setLevel(config.LOG_LEVEL)
_logger.addHandler(_h)
_logger.propagate = False


def _kv(**fields) -> str:
    return " ".join(f"{k}={v}" for k, v in fields.items())


def seg(event: str, **fields):
    """句子層級事件。fields 只接受 id / 數字 / 列舉，不接受內容。"""
    _logger.info("%s %s", event, _kv(**fields))


def info(event: str, **fields):
    _logger.info("%s %s", event, _kv(**fields))


def warn(event: str, **fields):
    _logger.warning("%s %s", event, _kv(**fields))


def error(event: str, **fields):
    # 注意：不要在這裡無腦開 exc_info=True ——
    # 堆疊可能把音訊或文字吐出來。要開之前先確認。
    _logger.error("%s %s", event, _kv(**fields))
''')

f("app/protocol.py", r'''
"""
訊息格式的唯一真實來源。

前後端都照這份。改這裡的時候記得同步 web/js/store.js。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Layer(str, Enum):
    ASR = "ASR"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass
class Segment:
    """
    Server → Client。

    重要規則:
      id       偵測到開口的那一刻就發，不是等切完才發
      rev      單調遞增；前端收到比現有更舊的 rev 直接丟棄
      replaces L3 合併句子時用；前端刪除列表內全部 id，插入新的
    """
    id: str
    rev: int
    layer: Layer
    t_start: float
    t_end: float
    text: str = ""
    translation: Optional[str] = None
    replaces: list[str] = field(default_factory=list)

    def to_message(self) -> dict:
        return {
            "type": "segment",
            "id": self.id,
            "rev": self.rev,
            "layer": self.layer.value,
            "t_start": round(self.t_start, 2),
            "t_end": round(self.t_end, 2),
            "text": self.text,
            "translation": self.translation,
            "replaces": self.replaces,
        }


# Client → Server
#   {"type": "start", "source_lang": "zh", "target_lang": "en",
#    "glossary": ["Zenoh", "ROS 2"]}
#   {"type": "audio", "seq": 1234}        // 後接 binary frame
#   {"type": "stop"}
#   {"type": "ping"}
''')

f("app/main.py", r'''
"""FastAPI 進入點。掛靜態檔、/healthz、/stats、WebSocket。"""
# TODO(S1-1)
''')

f("app/ws.py", r'''
"""
WebSocket 端點。

負責:
  - 接收 binary 音訊 frame → ring buffer
  - 驅動 segmenter，拿到 Cut 就交給 layers/asr.py
  - heartbeat（S2-5）
  - 斷線時釋放 session 記憶體

不負責: 任何切句決策邏輯（那在 audio/segmenter.py）
"""
# TODO(S1-2, S1-4)
''')

f("app/session.py", r'''
"""
Session 生命週期。

零保存的關鍵：斷線時所有狀態必須確實釋放。
S4-4 稽核會驗這一點（講 30 分鐘後斷線，觀察 RSS 回落）。
"""
# TODO(S1-3)
''')

f("app/stats.py", r'''
"""
/stats 聚合數字。記憶體環形統計，不落地。

只有聚合數字，絕不含內容。

S1 要量的:
  - ASR 往返 p50 / p95 / p99     → 決定要不要接 AORUS
  - 片段長度分布                  → 驗證切句參數
  - 切句原因統計 SOFT/HARD/MAX    → MAX 佔比高 = 影子視窗很重要

判讀:
  p95 < 1.5s     AORUS 完全不用接
  p95 1.5~3s     符合預期
  p95 > 3s       考慮接 AORUS 當第二路由

  MAX 佔比 < 5%   S5 影子視窗優先度可降低
  MAX 佔比 > 15%  S5 別跳過
"""
# TODO(S1-7)
''')

# ── app/audio/ ────────────────────────────────────────────────

f("app/audio/__init__.py", "")

f("app/audio/segmenter.py", r'''
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
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app import config


class CutReason(str, Enum):
    HARD = "HARD"          # 靜音超過 HARD_SILENCE_MS
    SOFT_PROSODY = "SOFT"  # 靜音達 SOFT 且 F0 下降（S5+，先不實作）
    MAX = "MAX"            # 撞到 MAX_SEGMENT_MS 保險絲


@dataclass
class Cut:
    """一次切句決定。時間戳為 VAD 精確邊界，不含 padding。"""
    t_start: float
    t_end: float
    reason: CutReason


class Segmenter:
    """
    用法:

        seg = Segmenter()
        for t, prob in vad_stream:
            cut = seg.feed(t, prob)
            if cut:
                handle(cut)

    feed() 除了自身狀態外沒有任何副作用，因此可直接用在離線分析。
    """

    def __init__(self, cfg=config):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._speaking = False
        self._seg_start: Optional[float] = None
        self._last_voice_t: Optional[float] = None
        self._silence_started: Optional[float] = None

    def feed(self, t: float, speech_prob: float) -> Optional[Cut]:
        """
        餵入一個音框。

        t             該音框的起始時間（秒，session 起算）
        speech_prob   Silero VAD 輸出的語音機率 0~1

        回傳 Cut 表示此刻應該切；回傳 None 表示繼續累積。
        """
        raise NotImplementedError("TODO(S1-4)")
''')

f("app/audio/vad.py", r'''
"""
Silero VAD 包裝（ONNX runtime，CPU）。

輸出 (t, speech_prob) 串流給 segmenter.py。
模型約 1.8MB，每 32ms 音框約 0.1~0.5ms，約佔 Pi 5 一核的 2%。

這個模組只負責「這個音框是不是語音」，
不做任何切句決策 —— 那是 segmenter.py 的事。
"""
# TODO(S1-4)
''')

f("app/audio/ring_buffer.py", r'''
"""
環形緩衝區，保留最近 RING_BUFFER_SECONDS（25 秒）音訊。

S1 用途: 切片來源
S5 用途: 影子視窗要回頭取 [start+9s, start+21s]

驗收: 講 5 分鐘，記憶體用量持平不成長。
"""
# TODO(S1-3)
''')

f("app/audio/framing.py", r'''
"""
音訊切片、padding、PCM → wav。

★ padding 是必做項:
  切出來的音訊前後各補 PAD_BEFORE_MS / PAD_AFTER_MS。
  VAD 貼著發聲切，會削掉字首塞音（ㄅㄉㄍ、p/t/k）和字尾氣音，
  模型讀到削過的邊界，前後一兩個字就會錯。

  這個 bug 很難抓 —— 你用耳朵聽切出來的音檔覺得完全正常，
  但模型不是用耳朵聽的。

  padding 只影響送去解碼的音訊，不影響 segment 的時間戳。

送 NCHC 用 wav 不用 mp3:
  mp3 每次編碼多 50~150ms，而且 encoder 有 padding 延遲。
"""
# TODO(S1-4)
''')

# ── app/providers/ ────────────────────────────────────────────

f("app/providers/__init__.py", "")

f("app/providers/base.py", r'''
"""
外部服務抽象。

為什麼要介面: 現在只有 NCHC，但之後可能接 AORUS 當第二路由。
有介面的話那時只是多一個檔案，呼叫端一行都不用改。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ASRResult:
    text: str
    avg_logprob: float | None = None
    elapsed_ms: float = 0.0


class ASRProvider(ABC):
    @abstractmethod
    async def transcribe(
        self,
        wav_bytes: bytes,
        language: str,
        prompt: str = "",
    ) -> ASRResult: ...


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        model: str,
        messages: list[dict],
        stream: bool = False,
    ): ...
''')

f("app/providers/nchc_asr.py", r'''
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

★ 每次呼叫都要記錄往返時間 → stats.py
"""
# TODO(S1-6)
''')

f("app/providers/pool.py", r'''
"""
並行上限 + 指數退避重試。

NCHC 目前看起來沒有明文速率限制，但「沒有明文上限」通常意味著
有並行數上限，或負載高時默默變慢。這層是很便宜的保險，
可以免掉一類很難查的間歇性失敗。

    MAX_CONCURRENT_ASR = 2
    MAX_CONCURRENT_LLM = 3
    RETRY_MAX = 2

優先權: L1 最高（在關鍵路徑上），L2 可排隊等待。
"""
# TODO(S1-6)
''')

# ── app/layers/ ───────────────────────────────────────────────

f("app/layers/__init__.py", "")

f("app/layers/asr.py", r'''
"""
ASR 層。拿到 Cut → 取音訊 → padding → wav → NCHC → 推 Segment。

一層一檔的理由: L3 是最後才做而且可能不做，
它必須能整個不存在而系統照跑。
"""
# TODO(S1-6)
''')

# ══════════════════════════════════════════════════════════════
# web/
# ══════════════════════════════════════════════════════════════

f("web/index.html", r"""
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>rt-translate</title>
  <link rel="stylesheet" href="/css/style.css">
</head>
<body>
  <header id="setup">
    <!-- 按開始後整場鎖定，要換就開新 session -->
    <label>來源語言
      <select id="source-lang">
        <option value="zh">中文（含中英夾雜）</option>
        <option value="en">English</option>
        <option value="ja">日本語</option>
      </select>
    </label>
    <label>目標語言
      <select id="target-lang">
        <option value="en">English</option>
        <option value="zh">中文</option>
        <option value="ja">日本語</option>
      </select>
    </label>
    <label>術語清單（選填）
      <input id="glossary" placeholder="Zenoh, ROS 2, LiDAR">
    </label>
    <button id="start">開始</button>
    <span id="status">未連線</span>
  </header>

  <main>
    <canvas id="waveform" height="60"></canvas>
    <div id="transcript"></div>
  </main>

  <script type="module" src="/js/main.js"></script>
</body>
</html>
""")

f("web/css/style.css", r"""
/* S1 先求能看。視覺狀態（L1 淡色小點等）到 S3 再做。 */
:root {
  --fg: #1a1a1a;
  --muted: #888;
  --bg: #fff;
}
@media (prefers-color-scheme: dark) {
  :root { --fg: #e8e8e8; --muted: #777; --bg: #141414; }
}
body {
  margin: 0;
  font: 16px/1.7 system-ui, "Noto Sans TC", sans-serif;
  color: var(--fg);
  background: var(--bg);
}
#setup { display: flex; gap: 1rem; flex-wrap: wrap; align-items: end; padding: 1rem; }
main { padding: 1rem; }
#waveform { width: 100%; }
#transcript .seg { margin: .6rem 0; }
#transcript .seg .dst { color: var(--muted); }
""")

f("web/js/worklet/pcm-processor.js", r"""
/**
 * AudioWorklet processor — 16kHz mono Int16 PCM。
 *
 * ★ 必須是獨立檔案。AudioWorklet 用 URL 載入:
 *     await ctx.audioWorklet.addModule('/js/worklet/pcm-processor.js');
 *   它跑在另一個全域環境裡，不能 import 主執行緒的東西，
 *   也不能被打包進其他檔案。很多人第一次寫會在這裡卡住。
 *
 * 取樣率換算錯是最常見的 bug，症狀是聲音變快或變慢。
 * 驗收方式: 伺服器端存下一個 wav 播出來聽。
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // TODO(S1-2): 依 sampleRate → 16000 做重採樣
    // TODO(S1-2): 累積到 32ms 再 postMessage，不要每個 render quantum 都送
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    // TODO(S1-2): Float32 → Int16，postMessage 給主執行緒
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
""")

f("web/js/main.js", r"""
// 組裝與設定列。S1 只要能按下開始、拿到字。
// TODO(S1-2, S1-8)
""")

f("web/js/audio.js", r"""
// getUserMedia → AudioWorklet → 16kHz mono Int16 PCM → socket
// 不要用已棄用的 ScriptProcessorNode。
// TODO(S1-2)
""")

f("web/js/socket.js", r"""
// WebSocket 連線。S2 再加 heartbeat 與自動重連。
//
// heartbeat 是必需品不是加分項:
//   Cloudflare 對閒置的 WebSocket 約 100 秒就會斷線。
//   驗收要實測 —— 故意沉默 3 分鐘。
// TODO(S1-2)
""")

f("web/js/render.js", r"""
// 畫面繪製。
// S1: 收到文字就 append，先不做 upsert。
// S2: 改用 store.js 的 Map。
// TODO(S1-8)
""")

# ══════════════════════════════════════════════════════════════
# tools/
# ══════════════════════════════════════════════════════════════

f("tools/visualize_segmentation.py", r'''
"""
切句視覺化。★ 不是可選的。

    python tools/visualize_segmentation.py tests/fixtures/sample.wav

輸出一張圖到 tools/out/:
    ├─ 波形
    ├─ VAD 機率曲線 + 門檻線
    └─ 切點標記（含觸發原因 SOFT/HARD/MAX）

為什麼必做: 調那五個門檻值時，看圖比看數字快一個量級。
半小時的投入會在 S1-4 省下好幾小時。

★ 必須 import app.audio.segmenter 的同一個 Segmenter，
  不可以在這裡另外寫一份邏輯 —— 否則圖上調出來的參數
  不等於線上跑的參數。
"""
# TODO(S1-5)
''')

f("tools/probe_nchc.py", r'''
"""
探測 NCHC 端點能力。

已確認:
  OK  client.audio.transcriptions.create 可用
  OK  language 參數
  OK  prompt 參數
  OK  wav 輸入
  OK  無明文速率限制

待確認:
  ?   模型清單裡有沒有 Breeze-ASR-25
      → 影響 S2-4 中文路由。沒有的話改用 large-v3-turbo，
        中英夾雜品質會下降但可用。
  ?   verbose_json 有沒有回 avg_logprob
      → 影響 S2-3 切早了的判定。沒有的話只能靠標點 + 時長。
"""
# TODO
''')

# ══════════════════════════════════════════════════════════════
# tests/
# ══════════════════════════════════════════════════════════════

f("tests/__init__.py", "")

f("tests/test_segmenter.py", r'''
"""
Segmenter 測試。純函式，最好測 —— 直接餵合成的機率序列。

必測案例:
  1. 想詞停頓（300ms 靜音後又有聲音）→ 不該切
  2. 真句尾（>800ms 靜音）→ 該切，reason=HARD
  3. 連續講 12 秒不停 → 該切，reason=MAX
  4. 極短片段（<500ms）→ 併入前段，不獨立成句
  5. hangover 取消: SOFT 倒數中又有聲音 → 倒數歸零
"""
import pytest

from app.audio.segmenter import Segmenter, CutReason


@pytest.mark.skip(reason="TODO(S1-4)")
def test_thinking_pause_does_not_cut():
    ...


@pytest.mark.skip(reason="TODO(S1-4)")
def test_sentence_end_cuts_with_hard_reason():
    ...


@pytest.mark.skip(reason="TODO(S1-4)")
def test_max_segment_fuse():
    ...
''')

f("tests/fixtures/.gitkeep", "")

f("prompts/.gitkeep", "")


# ══════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="rt-translate S1 骨架產生器")
    ap.add_argument("root", nargs="?", default=".",
                    help="目標目錄（預設：目前目錄）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出會建什麼，不實際寫入")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    print(f"rt-translate scaffold -> {root}")
    if args.dry_run:
        print("(dry-run：不會寫入任何檔案)")
    print()

    new = skipped = 0

    for rel, content in FILES.items():
        target = root / rel

        if target.exists():
            print(f"  skip   {rel}")
            skipped += 1
            continue

        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            # newline="\n" — 就算在 Windows 上跑也一律寫 LF
            target.write_text(content, encoding="utf-8", newline="\n")
        print(f"  new    {rel}")
        new += 1

    print()
    print(f"完成 — 新增 {new} 個，跳過 {skipped} 個。")

    if new and not args.dry_run:
        print()
        print("下一步:")
        print(f"  cd {root}")
        print(r"  python -m venv .venv")
        print(r"  .venv\Scripts\activate")
        print(r'  pip install -e ".[dev]"')
        print(r"  copy .env.example .env")
        print()
        print("S1 的核心是 segmenter.py（純邏輯，不碰 I/O）。")
        print("建議先寫它和 test_segmenter.py，再接音訊管線。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
