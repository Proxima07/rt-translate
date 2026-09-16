"""
WebSocket 端點。

負責:
  - 接收 binary 音訊 frame → ring buffer → VAD → Segmenter
  - 把 Cut 丟進 session 專屬佇列，由單一 worker 依序處理
  - heartbeat（S2-5）
  - 斷線時釋放 session 記憶體

不負責: 任何切句決策邏輯（那在 audio/segmenter.py）

★ 為什麼 Cut 要走佇列而不是直接 create_task:
  ASR 是網路呼叫，結果會亂序回來。
  但 S2-3 的合併判定需要「這一段」和「下一段」有明確先後，
  亂序的話合併對象會錯。每個 session 一個 worker 依序處理，
  邏輯就是決定性的 —— 而且反正一個人一次只講一句話，
  session 內序列化不會損失任何吞吐。
"""
import asyncio
import json

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from app import config, logging_ as log, stats
from app.layers.asr import ASRLayer
from app.protocol import Segment
from app.session import Session

_active: set[str] = set()


async def endpoint(ws: WebSocket, asr: ASRLayer) -> None:
    await ws.accept()
    sess: Session | None = None
    queue: asyncio.Queue = asyncio.Queue()
    worker: asyncio.Task | None = None

    try:
        while True:
            msg = await ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            # ── binary：音訊 ──
            if (raw := msg.get("bytes")) is not None:
                if sess is None:
                    continue
                pcm = np.frombuffer(raw, dtype=np.int16)
                sess.ring.write(pcm)
                sess.observe_level(pcm)

                for t, prob in sess.vad.feed(pcm):
                    sess.observe(prob)
                    if (cut := sess.segmenter.feed(t, prob)) is not None:
                        sess.cuts += 1
                        log.seg("cut", reason=cut.reason.value,
                                ms=round(cut.duration_ms))
                        for c in sess.shortcuts.feed(cut):
                            queue.put_nowait(c)

                # ★ 每 2 秒回報一次「伺服器到底聽到什麼」。
                #   這是診斷的關鍵：音訊有沒有進來、VAD 有沒有判定為語音、
                #   有沒有切出句子 —— 三件事分開看才知道斷在哪一段。
                if (h := sess.heard()) is not None:
                    log.info("heard", **h)
                    await _send(ws, {"type": "heard", **h})

                if (state := sess.speaking_changed()) is not None:
                    await _send(ws, {"type": "speaking", "active": state})
                continue

            # ── text：控制訊息 ──
            text = msg.get("text")
            if not text:
                continue
            data = json.loads(text)
            kind = data.get("type")

            if kind == "client":
                log.info("client", rate=data.get("sample_rate"),
                         mic=(data.get("device") or "?")[:40])

            elif kind == "ping":
                # ★ Cloudflare 對閒置的 WebSocket 約 100 秒就斷。
                #   前端每 30 秒 ping，這裡一定要回。
                await _send(ws, {"type": "pong"})

            elif kind == "start":
                if len(_active) >= config.MAX_SESSIONS:
                    await _send(ws, {"type": "error",
                                     "code": "busy",
                                     "message": "同時使用人數已達上限，請稍後再試"})
                    break
                sess = Session(
                    source_lang=data.get("source_lang", "zh"),
                    target_lang=data.get("target_lang", "en"),
                    glossary=data.get("glossary") or [],
                )
                _active.add(sess.id)
                stats.bump("sessions")
                log.info("session_start", sid=sess.id,
                         src=sess.source_lang, dst=sess.target_lang,
                         rate=data.get("sample_rate", "?"),
                         mic=(data.get("device") or "?")[:40])
                worker = asyncio.create_task(_worker(ws, sess, queue, asr))
                await _send(ws, {"type": "ready", "session_id": sess.id})

            elif kind == "stop":
                if sess is not None:
                    if (tail := sess.segmenter.flush()) is not None:
                        for c in sess.shortcuts.feed(tail):
                            queue.put_nowait(c)
                    for c in sess.shortcuts.flush():
                        queue.put_nowait(c)
                await queue.join()
                await _send(ws, {"type": "stopped"})
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:                                   # noqa: BLE001
        log.error("ws_error", err=type(e).__name__)
    finally:
        if worker is not None:
            worker.cancel()
        if sess is not None:
            _active.discard(sess.id)
            log.info("session_end", sid=sess.id)
            # ★ 零保存：斷線即釋放，不等 GC 心情好
            sess.close()


async def _worker(ws: WebSocket, sess: Session, queue: asyncio.Queue,
                  asr: ASRLayer) -> None:
    """單一 worker 依序處理 Cut，確保合併邏輯是決定性的。"""
    while True:
        cut = await queue.get()
        try:
            for seg in await asr.handle_cut(sess, cut):
                await _push(ws, sess, seg)
        except Exception as e:                               # noqa: BLE001
            # 單一片段失敗不該讓整個 session 掛掉 ——
            # 但也絕不能靜音失敗。使用者看到的必須是「壞了」，
            # 而不是跟「還沒講話」長得一模一樣的空白畫面。
            log.error("cut_failed", err=type(e).__name__)
            stats.bump("asr_failed")
            await _send(ws, {
                "type": "notice", "level": "error",
                "message": _explain(e),
            })
        finally:
            queue.task_done()


async def _push(ws: WebSocket, sess: Session, seg: Segment) -> None:
    await _send(ws, seg.to_message())


async def _send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception:                                        # noqa: BLE001
        pass


def _explain(e: Exception) -> str:
    """把例外翻成使用者看得懂、而且指得出下一步的話。"""
    name = type(e).__name__
    text = str(e)
    if isinstance(e, ValueError) and "ASR 模型" in text:
        return "沒有設定辨識模型，請檢查 .env 的 NCHC_ASR_MODEL_*"
    if "Authentication" in name or "401" in text or "403" in text:
        return "NCHC 金鑰被拒絕，請檢查 .env 的 NCHC_API_KEY"
    if "Connection" in name or "Timeout" in name:
        return "連不上 NCHC，請檢查 .env 的 NCHC_BASE_URL 與網路"
    if "NotFound" in name or "404" in text:
        return "NCHC 找不到這個模型，請用 tools/check_nchc.py 看可用清單"
    return f"辨識失敗（{name}）"
