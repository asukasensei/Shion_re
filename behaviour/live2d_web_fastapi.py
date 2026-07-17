from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from contracts.frontend import FrontendEvent

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from behaviour.avatar.live2d_web import Live2DWebServer


def create_live2d_app(server: "Live2DWebServer") -> FastAPI:
    app = FastAPI(title="Shion Desktop Gateway", docs_url=None, redoc_url=None)
    renderer_dir = server.renderer_dir

    if renderer_dir.is_dir():
        app.mount(
            "/renderer",
            StaticFiles(directory=str(renderer_dir)),
            name="renderer",
        )
    app.mount(
        "/live2d-model",
        StaticFiles(directory=str(server.config.model_dir)),
        name="live2d-model",
    )

    @app.get("/")
    async def index() -> FileResponse:
        index_path = renderer_dir / "index.html"
        if not index_path.is_file():
            raise HTTPException(503, "Electron renderer assets are missing")
        return FileResponse(index_path)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "sequence": server.frontend_bus.sequence,
            "desktop_channel": server.desktop_channel is not None,
        }

    @app.get("/api/config")
    async def client_config() -> dict[str, Any]:
        return server.client_config()

    @app.get("/vendor/{asset_name}")
    async def vendor_asset(asset_name: str) -> FileResponse:
        path = server.vendor_asset(asset_name)
        if path is None:
            raise HTTPException(404, f"Vendor asset not installed: {asset_name}")
        return FileResponse(path)

    @app.get("/media/audio/{audio_id}")
    async def audio(audio_id: str, token: str = Query(default="")) -> FileResponse:
        server.validate_token(token)
        path = server.resolve_audio(audio_id)
        if path is None:
            raise HTTPException(404, "Audio not found")
        return FileResponse(path)

    @app.get("/events")
    async def poll_events(
        client_id: str = Query(default="desktop-local"),
        after: int = Query(default=0, ge=0),
        token: str = Query(default=""),
    ) -> JSONResponse:
        server.validate_token(token)
        subscription = server.frontend_bus.subscribe(client_id, after_seq=after)
        try:
            event = await asyncio.to_thread(subscription.get, 25.0)
            return JSONResponse(event.to_dict() if event else {"type": "timeout"})
        finally:
            subscription.close()

    @app.websocket("/ws/desktop")
    async def desktop_socket(websocket: WebSocket) -> None:
        client_id = websocket.query_params.get("client_id", "desktop-local")
        token = websocket.query_params.get("token", "")
        try:
            server.validate_token(token)
        except HTTPException:
            await websocket.close(code=1008, reason="invalid token")
            return

        try:
            after_seq = int(websocket.query_params.get("after_seq", "0"))
        except ValueError:
            after_seq = 0
        await websocket.accept()
        subscription = server.frontend_bus.subscribe(
            client_id,
            after_seq=max(after_seq, 0),
        )

        sender = asyncio.create_task(_send_events(websocket, subscription))
        receiver = asyncio.create_task(
            _receive_events(websocket, server, client_id)
        )
        server.frontend_bus.publish_event(
            "system.ready",
            server.client_config(),
            target_client_id=client_id,
        )
        try:
            done, pending = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            subscription.close()

    return app


async def _send_events(websocket: WebSocket, subscription: Any) -> None:
    while True:
        event = await asyncio.to_thread(subscription.get, 0.5)
        if event is None:
            continue
        await websocket.send_json(event.to_dict())


async def _receive_events(
    websocket: WebSocket,
    server: "Live2DWebServer",
    client_id: str,
) -> None:
    recording: dict[str, Any] | None = None
    chunks = bytearray()
    while True:
        packet = await websocket.receive()
        packet_type = packet.get("type")
        if packet_type == "websocket.disconnect":
            raise WebSocketDisconnect(packet.get("code", 1000))

        binary = packet.get("bytes")
        if binary is not None:
            if recording is None:
                await _send_error(server, client_id, "audio.begin is required")
                continue
            if len(chunks) + len(binary) > server.config.max_audio_bytes:
                recording = None
                chunks.clear()
                await _send_error(server, client_id, "audio message is too large")
                continue
            chunks.extend(binary)
            continue

        text = packet.get("text")
        if text is None:
            continue
        try:
            raw = json.loads(text)
            event = FrontendEvent.from_dict(raw)
            if event.type == "ping":
                server.frontend_bus.publish_event(
                    "pong",
                    {"source_event_id": event.event_id},
                    target_client_id=client_id,
                )
            elif event.type == "client.hello":
                server.frontend_bus.publish_event(
                    "client.welcome",
                    server.client_config(),
                    session_id=event.session_id,
                    target_client_id=client_id,
                )
            elif event.type == "input.audio.begin":
                recording = dict(event.payload)
                recording["source_event"] = event
                chunks.clear()
                server.frontend_bus.publish_event(
                    "input.recording",
                    {"audio_id": recording.get("audio_id")},
                    session_id=event.session_id,
                    target_client_id=client_id,
                )
            elif event.type == "input.audio.end":
                if recording is None:
                    raise ValueError("audio.end received before audio.begin")
                source_event = recording.pop("source_event")
                recording.update(event.payload)
                audio_event = await server.process_audio(
                    bytes(chunks),
                    recording,
                    source_event=source_event,
                    client_id=client_id,
                )
                recording = None
                chunks.clear()
                server.accept_frontend_event(audio_event, client_id=client_id)
            elif event.type == "client.error":
                logger.error(
                    "Desktop client error [%s] %s: %s\n%s",
                    client_id,
                    event.payload.get("stage", "unknown"),
                    event.payload.get("message", "unknown error"),
                    event.payload.get("stack", ""),
                )
            else:
                server.accept_frontend_event(event, client_id=client_id)
        except (
            ValueError,
            TypeError,
            RuntimeError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            recording = None
            chunks.clear()
            await _send_error(server, client_id, str(exc))


async def _send_error(
    server: "Live2DWebServer",
    client_id: str,
    message: str,
) -> None:
    server.frontend_bus.publish_event(
        "error",
        {"message": message},
        target_client_id=client_id,
    )
