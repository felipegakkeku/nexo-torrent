from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import libtorrent as lt
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import AppConfig
from engine import NexoTorrentEngine
from hardware import should_use_staging
from trackers import refresh_trackers_async


class MagnetRequest(BaseModel):
    uri: str
    save_path: str | None = None
    use_staging: bool | None = None
    sequential: bool = False
    prioritize_ends: bool = False
    start_paused: bool = False
    boost_trackers: bool | None = None


class StagingCheckRequest(BaseModel):
    save_path: str
    total_size: int = 0


class TorrentOptionsRequest(BaseModel):
    sequential: bool | None = None
    prioritize_ends: bool | None = None
    download_limit_kbps: int | None = None
    upload_limit_kbps: int | None = None


class FilePrioritiesRequest(BaseModel):
    priorities: list[int]


def create_app(
    api_token: str = "",
    on_shutdown_request: Any = None,
) -> FastAPI:
    pending_events: list[dict[str, Any]] = []

    def _on_finished(torrent_summary: dict[str, Any]) -> None:
        pending_events.append(
            {
                "type": "torrent_finished",
                "info_hash": torrent_summary["info_hash"],
                "name": torrent_summary["name"],
                "final_save_path": torrent_summary["final_save_path"],
            }
        )

    engine = NexoTorrentEngine(on_torrent_finished=_on_finished)
    ws_clients: dict[WebSocket, str | None] = {}
    stop_event = asyncio.Event()

    async def _ticker_loop() -> None:
        try:
            await refresh_trackers_async(force=False)
        except Exception:
            pass
        while not stop_event.is_set():
            try:
                snapshot = await asyncio.to_thread(engine.tick)
                events = list(pending_events)
                pending_events.clear()

                dead: list[WebSocket] = []
                details_cache: dict[str, dict[str, Any] | None] = {}
                for ws, sub_hash in list(ws_clients.items()):
                    details = None
                    if sub_hash:
                        if sub_hash not in details_cache:
                            details_cache[sub_hash] = await asyncio.to_thread(
                                engine.get_torrent_details, sub_hash
                            )
                        details = details_cache[sub_hash]
                    payload = {
                        "type": "state",
                        "data": snapshot,
                        "details": details,
                        "events": events,
                    }
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    ws_clients.pop(ws, None)
            except Exception:
                pass

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(_ticker_loop())
        try:
            yield
        finally:
            stop_event.set()
            await task
            await asyncio.to_thread(engine.shutdown)

    app = FastAPI(title="Nexo Torrent Engine", version="1.1.1", lifespan=lifespan)
    app.state.engine = engine

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)
        if api_token and request.url.path.startswith("/api/"):
            header_tok = request.headers.get("X-Nexo-Token", "")
            if header_tok != api_token:
                return JSONResponse({"detail": "Não autorizado."}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "libtorrent": lt.__version__}

    @app.get("/api/state")
    async def get_state():
        return await asyncio.to_thread(engine.get_state_snapshot, False)

    @app.get("/api/system/hardware")
    async def get_hardware():
        hw = await asyncio.to_thread(engine.get_hardware, True)
        return hw.model_dump()

    @app.post("/api/system/staging-check")
    async def check_staging(body: StagingCheckRequest):
        hw = await asyncio.to_thread(engine.get_hardware, True)
        use_stg, reason = should_use_staging(body.save_path, body.total_size, engine.cfg, hw)
        return {"use_staging": use_stg, "reason": reason}

    @app.post("/api/system/shutdown")
    async def system_shutdown():
        if on_shutdown_request:
            on_shutdown_request()
        return {"ok": True}

    @app.get("/api/config")
    async def get_config():
        return engine.cfg.model_dump()

    @app.put("/api/config")
    async def update_config(body: AppConfig):
        saved = await asyncio.to_thread(engine.apply_config, body)
        return saved.model_dump()

    @app.post("/api/torrents/inspect")
    async def inspect_torrent(file: UploadFile = File(...)):
        raw = await file.read()
        try:
            return await asyncio.to_thread(engine.inspect_torrent_bytes, raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Arquivo .torrent inválido: {exc}")

    @app.post("/api/torrents/magnet")
    async def add_magnet(body: MagnetRequest):
        if not body.uri.strip().lower().startswith("magnet:?"):
            raise HTTPException(status_code=400, detail="Link magnet inválido.")
        try:
            return await asyncio.to_thread(
                engine.add_magnet,
                body.uri,
                body.save_path,
                body.use_staging,
                body.sequential,
                body.prioritize_ends,
                body.start_paused,
                body.boost_trackers,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Erro ao adicionar magnet: {exc}")

    @app.post("/api/torrents/file")
    async def add_torrent_file(
        file: UploadFile = File(...),
        save_path: str | None = Form(default=None),
        use_staging: str | None = Form(default=None),
        sequential: bool = Form(default=False),
        prioritize_ends: bool = Form(default=False),
        start_paused: bool = Form(default=False),
        boost_trackers: str | None = Form(default=None),
        file_priorities: str | None = Form(default=None),
    ):
        raw = await file.read()
        parsed_prios: list[int] | None = None
        if file_priorities:
            try:
                parsed_prios = json.loads(file_priorities)
            except Exception:
                raise HTTPException(status_code=400, detail="Prioridades de arquivo inválidas.")

        stg_val: bool | None = None
        if use_staging is not None and use_staging != "" and use_staging.lower() != "auto":
            stg_val = use_staging.lower() == "true"

        boost_val: bool | None = None
        if boost_trackers is not None and boost_trackers != "" and boost_trackers.lower() != "auto":
            boost_val = boost_trackers.lower() == "true"

        try:
            return await asyncio.to_thread(
                engine.add_torrent_bytes,
                raw,
                save_path,
                parsed_prios,
                stg_val,
                sequential,
                prioritize_ends,
                start_paused,
                boost_val,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Erro ao adicionar .torrent: {exc}")

    @app.post("/api/torrents/pause-all")
    async def pause_all():
        count = await asyncio.to_thread(engine.pause_all)
        return {"count": count}

    @app.post("/api/torrents/resume-all")
    async def resume_all():
        count = await asyncio.to_thread(engine.resume_all)
        return {"count": count}

    @app.post("/api/torrents/{info_hash}/pause")
    async def pause_torrent(info_hash: str):
        if not await asyncio.to_thread(engine.pause, info_hash):
            raise HTTPException(status_code=404, detail="Torrent não encontrado.")
        return {"ok": True}

    @app.post("/api/torrents/{info_hash}/resume")
    async def resume_torrent(info_hash: str):
        if not await asyncio.to_thread(engine.resume, info_hash):
            raise HTTPException(status_code=404, detail="Torrent não encontrado.")
        return {"ok": True}

    @app.post("/api/torrents/{info_hash}/recheck")
    async def recheck_torrent(info_hash: str):
        if not await asyncio.to_thread(engine.recheck, info_hash):
            raise HTTPException(status_code=404, detail="Torrent não encontrado.")
        return {"ok": True}

    @app.post("/api/torrents/{info_hash}/reannounce")
    async def reannounce_torrent(info_hash: str):
        if not await asyncio.to_thread(engine.force_reannounce, info_hash):
            raise HTTPException(status_code=404, detail="Torrent não encontrado.")
        return {"ok": True}

    @app.post("/api/torrents/{info_hash}/boost-trackers")
    async def boost_torrent_trackers(info_hash: str):
        return await asyncio.to_thread(engine.boost_trackers, info_hash)

    @app.patch("/api/torrents/{info_hash}/options")
    async def update_torrent_options(info_hash: str, body: TorrentOptionsRequest):
        ok = await asyncio.to_thread(
            engine.set_options,
            info_hash,
            body.sequential,
            body.prioritize_ends,
            body.download_limit_kbps,
            body.upload_limit_kbps,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Torrent não encontrado.")
        return {"ok": True}

    @app.patch("/api/torrents/{info_hash}/files")
    async def update_file_priorities(info_hash: str, body: FilePrioritiesRequest):
        ok = await asyncio.to_thread(engine.set_file_priorities, info_hash, body.priorities)
        if not ok:
            raise HTTPException(status_code=404, detail="Torrent não encontrado.")
        return {"ok": True}

    @app.delete("/api/torrents/{info_hash}")
    async def remove_torrent(info_hash: str, delete_files: bool = Query(default=False)):
        ok = await asyncio.to_thread(engine.remove, info_hash, delete_files)
        if not ok:
            raise HTTPException(status_code=404, detail="Torrent não encontrado.")
        return {"ok": True}

    @app.get("/api/torrents/{info_hash}/details")
    async def get_torrent_details(info_hash: str):
        details = await asyncio.to_thread(engine.get_torrent_details, info_hash)
        if details is None:
            raise HTTPException(status_code=404, detail="Torrent não encontrado.")
        return details

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
        if api_token and token != api_token:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        ws_clients[websocket] = None
        try:
            snap = await asyncio.to_thread(engine.get_state_snapshot, False)
            await websocket.send_json({"type": "state", "data": snap, "details": None, "events": []})
            while True:
                msg = await websocket.receive_json()
                if isinstance(msg, dict) and "subscribe" in msg:
                    sub = msg.get("subscribe")
                    ws_clients[websocket] = str(sub).lower() if sub else None
                    if ws_clients[websocket]:
                        det = await asyncio.to_thread(engine.get_torrent_details, ws_clients[websocket])
                        await websocket.send_json({"type": "details", "details": det})
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            ws_clients.pop(websocket, None)

    return app
