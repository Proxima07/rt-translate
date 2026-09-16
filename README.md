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
