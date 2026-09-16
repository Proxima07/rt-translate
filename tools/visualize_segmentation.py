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
