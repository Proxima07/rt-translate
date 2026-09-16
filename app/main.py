"""FastAPI 進入點。掛靜態檔、/healthz、/stats、WebSocket。"""
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config, stats, ws
from app.layers.asr import ASRLayer
from app.providers.nchc_asr import NCHCASR

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="rt-translate", version="0.2.0")
_asr = ASRLayer(NCHCASR())


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/stats")
async def get_stats() -> dict:
    """★ 只有聚合數字，絕不含逐字稿內容。"""
    return stats.snapshot()


@app.websocket("/ws")
async def websocket(sock: WebSocket) -> None:
    await ws.endpoint(sock, _asr)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/js", StaticFiles(directory=WEB / "js"), name="js")
app.mount("/css", StaticFiles(directory=WEB / "css"), name="css")
