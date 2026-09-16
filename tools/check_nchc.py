"""
NCHC 連線與模型檢查。

    python tools/check_nchc.py                  # 列出可用模型
    python tools/check_nchc.py some.wav         # 實際跑一次辨識

這支獨立於整個服務，所以能把問題切乾淨:
  這裡通過 → 問題在音訊管線或前端
  這裡失敗 → 問題在 .env 或 NCHC

不會寫任何檔案，符合零保存。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI              # noqa: E402

from app import config                 # noqa: E402


def mask(s: str) -> str:
    return f"{s[:4]}…{s[-4:]}" if len(s) > 10 else ("(已填)" if s else "(空白)")


def main() -> int:
    print("── .env ──────────────────────────────")
    print(f"  NCHC_BASE_URL          {config.NCHC_BASE_URL or '(空白)'}")
    print(f"  NCHC_API_KEY           {mask(config.NCHC_API_KEY)}")
    print(f"  NCHC_ASR_MODEL_ZH      {config.NCHC_ASR_MODEL_ZH or '(空白)'}")
    print(f"  NCHC_ASR_MODEL_MULTI   {config.NCHC_ASR_MODEL_MULTI or '(空白)'}")
    print()

    if not config.NCHC_BASE_URL:
        print("✗ NCHC_BASE_URL 沒填。.env 是否放在專案根目錄？")
        return 1

    client = OpenAI(base_url=config.NCHC_BASE_URL,
                    api_key=config.NCHC_API_KEY or "unused")

    print("── 可用模型 ──────────────────────────")
    try:
        ids = sorted(m.id for m in client.models.list().data)
    except Exception as e:
        print(f"✗ 取不到模型清單: {type(e).__name__}: {e}")
        return 1

    asr = [i for i in ids if any(k in i.lower()
                                 for k in ("whisper", "asr", "breeze", "speech"))]
    print(f"  共 {len(ids)} 個，看起來像 ASR 的:")
    for i in (asr or ["(沒有找到)"]):
        print(f"    {i}")
    print()

    for label, name in (("ZH", config.NCHC_ASR_MODEL_ZH),
                        ("MULTI", config.NCHC_ASR_MODEL_MULTI)):
        if not name:
            print(f"  ! {label} 沒填")
        elif name in ids:
            print(f"  ✓ {label} = {name}")
        else:
            print(f"  ✗ {label} = {name}  ← 不在清單裡")
    print()

    if len(sys.argv) < 2:
        print("要實際測辨識: python tools/check_nchc.py some.wav")
        return 0

    wav = Path(sys.argv[1])
    if not wav.exists():
        print(f"✗ 找不到檔案: {wav}")
        return 1

    print("── 辨識測試 ──────────────────────────")
    import time
    t0 = time.perf_counter()
    try:
        r = client.audio.transcriptions.create(
            model=config.NCHC_ASR_MODEL_ZH or config.NCHC_ASR_MODEL_MULTI,
            file=("audio.wav", wav.read_bytes(), "audio/wav"),
            language="zh",
            prompt="",
            response_format="verbose_json",
        )
    except Exception as e:
        print(f"✗ {type(e).__name__}: {e}")
        return 1

    ms = (time.perf_counter() - t0) * 1000
    print(f"  往返 {ms:.0f} ms")
    print(f"  文字 {getattr(r, 'text', '')!r}")

    segs = getattr(r, "segments", None)
    if segs:
        lps = [getattr(s, "avg_logprob", None) for s in segs]
        lps = [v for v in lps if v is not None]
        print(f"  segments {len(segs)} 個，avg_logprob "
              f"{'有' if lps else '沒有'}")
        if not lps:
            print("    → merge.py 會退回用「標點 + 時長」判斷切早了，這是預期的降級")
    else:
        print("  ! verbose_json 沒回 segments，同上降級")
    return 0


if __name__ == "__main__":
    sys.exit(main())
