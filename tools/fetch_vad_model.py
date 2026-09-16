"""
取得 Silero VAD 的 ONNX 模型檔。

    python tools/fetch_vad_model.py

為什麼不直接 pip install silero-vad:
  那個套件的 metadata 硬性要求 torch>=1.12 + torchaudio，
  就算只裝 [onnx-cpu] extra 也會拉下來。
  Pi 5 ARM64 上那是幾百 MB，而我們只需要 ONNX 推論。

  但它的 wheel 裡面就包著模型檔，所以下載 wheel、解開、取檔就好。

取完之後把 app/audio/models/*.onnx 一起 commit 進 repo（1.26MB），
部署時就不用擔心網路。
"""
import glob
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WANT = "silero_vad_16k_op15.onnx"   # 我們固定 16kHz，用這顆
DEST = Path(__file__).resolve().parent.parent / "app" / "audio" / "models"


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    out = DEST / WANT
    if out.exists():
        print(f"已存在，跳過: {out}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        print("下載 silero-vad wheel（不裝，只取模型檔）...")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "download", "silero-vad",
             "--no-deps", "-d", tmp],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(r.stderr)
            return 1

        wheels = glob.glob(f"{tmp}/*.whl")
        if not wheels:
            print("找不到 wheel")
            return 1

        with zipfile.ZipFile(wheels[0]) as z:
            member = next((n for n in z.namelist() if n.endswith(WANT)), None)
            if member is None:
                print(f"wheel 裡沒有 {WANT}，實際內容:")
                print([n for n in z.namelist() if n.endswith(".onnx")])
                return 1
            with z.open(member) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)

    print(f"完成: {out}  ({out.stat().st_size / 1024:.0f} KB)")
    print("記得 commit 進 repo。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
