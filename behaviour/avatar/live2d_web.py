from __future__ import annotations

import asyncio
import math
import mimetypes
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import uvicorn
from fastapi import HTTPException

from behaviour.behaviour import Behaviour, BehaviourData
from behaviour.behaviour_bus import BehaviourBus
from channel.desktop import DesktopChannel
from config.config import Config
from contracts.frontend import FrontendEvent
from message.message_bus import MessageBus
from model_use.asr import ASRService


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MODEL_DIR = PROJECT_ROOT / "live2d_model" / "晴雨"
DEFAULT_MODEL_FILE = "晴雨.model3.json"


EXPRESSION_MAP = {
    "normal": None,
    "happy": "猫猫嘴.exp3.json",
    "joy": "猫猫嘴.exp3.json",
    "joy_high": "星星眼.exp3.json",
    "affection": "脸红.exp3.json",
    "affection_high": "爱心眼.exp3.json",
    "sad": "哭哭.exp3.json",
    "anger": "生气.exp3.json",
    "angry": "生气.exp3.json",
    "confused": "问号.exp3.json",
    "speechless": "无语.exp3.json",
    "surprise": "感叹号.exp3.json",
    "embarrassed": "脸红.exp3.json",
    "dizzy": "眩晕.exp3.json",
    "sweat": "汗滴.exp3.json",
}


def _numeric_parameters(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    parameters: dict[str, float] = {}
    for raw_id, raw_value in raw.items():
        parameter_id = str(raw_id).strip()
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if parameter_id and math.isfinite(value):
            parameters[parameter_id] = value
    return parameters


@dataclass(slots=True)
class Live2DWebConfig:
    enabled: bool = True
    auto_open: bool = True
    launch_electron: bool = True
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    model_dir: Path = DEFAULT_MODEL_DIR
    model_file: str = DEFAULT_MODEL_FILE
    token: str = ""
    max_audio_bytes: int = 20 * 1024 * 1024
    touch_cooldown_ms: int = 1200
    persistent_parameters: dict[str, float] = field(default_factory=dict)


class Live2DWebServer:
    def __init__(
        self,
        config: Live2DWebConfig | None = None,
        *,
        message_bus: MessageBus | None = None,
        frontend_bus: BehaviourBus | None = None,
        asr: ASRService | None = None,
    ) -> None:
        self.config = config or Live2DWebConfig()
        self.config.model_dir = Path(self.config.model_dir).expanduser().resolve()
        self.frontend_bus = frontend_bus or BehaviourBus()
        self.desktop_channel = (
            DesktopChannel(
                message_bus,
                self.frontend_bus,
                touch_cooldown_ms=self.config.touch_cooldown_ms,
            )
            if message_bus
            else None
        )
        self.asr = asr or ASRService()
        self.renderer_dir = Path(__file__).with_name("desktop") / "renderer"
        self.desktop_dir = self.renderer_dir.parent
        self.media_dir = PROJECT_ROOT / ".shion" / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._audio: dict[str, Path] = {}
        self._uvicorn: uvicorn.Server | None = None
        self._thread: Thread | None = None
        self._electron: subprocess.Popen | None = None
        self._url: str | None = None
        self._token = self.config.token or secrets.token_urlsafe(24)

    @classmethod
    def from_config(
        cls,
        *,
        message_bus: MessageBus | None = None,
        frontend_bus: BehaviourBus | None = None,
    ) -> "Live2DWebServer":
        settings = Config().config.get("live2d", {})
        model_dir = Path(settings.get("model_dir", DEFAULT_MODEL_DIR))
        if not model_dir.is_absolute():
            model_dir = PROJECT_ROOT / model_dir
        config = Live2DWebConfig(
            enabled=bool(settings.get("enabled", True)),
            auto_open=bool(settings.get("auto_open", True)),
            launch_electron=bool(settings.get("launch_electron", True)),
            host=str(settings.get("host", DEFAULT_HOST)),
            port=int(settings.get("port", DEFAULT_PORT)),
            model_dir=model_dir,
            model_file=str(settings.get("model_file", DEFAULT_MODEL_FILE)),
            token=str(settings.get("token", "")),
            max_audio_bytes=int(
                settings.get("max_audio_bytes", 20 * 1024 * 1024)
            ),
            touch_cooldown_ms=max(
                0,
                int(settings.get("touch_cooldown_ms", 1200)),
            ),
            persistent_parameters=_numeric_parameters(
                settings.get("persistent_parameters", {})
            ),
        )
        return cls(
            config,
            message_bus=message_bus,
            frontend_bus=frontend_bus,
        )

    def start(self, open_browser: bool | None = None) -> str | None:
        if not self.config.enabled:
            return None
        if self._thread and self._thread.is_alive():
            return self._url
        if not (self.config.model_dir / self.config.model_file).is_file():
            raise FileNotFoundError(
                f"Live2D model not found: "
                f"{self.config.model_dir / self.config.model_file}"
            )

        port = self.config.port or _find_free_port(self.config.host)
        from behaviour.live2d_web_fastapi import create_live2d_app

        app = create_live2d_app(self)
        uvicorn_config = uvicorn.Config(
            app,
            host=self.config.host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self._uvicorn = uvicorn.Server(uvicorn_config)
        self._thread = Thread(
            target=self._uvicorn.run,
            name="desktop-fastapi",
            daemon=True,
        )
        self._thread.start()
        deadline = time.monotonic() + 8
        while not self._uvicorn.started and self._thread.is_alive():
            if time.monotonic() >= deadline:
                raise TimeoutError("FastAPI desktop gateway did not start")
            time.sleep(0.02)
        if not self._thread.is_alive():
            raise RuntimeError("FastAPI desktop gateway stopped during startup")

        self._url = f"http://{self.config.host}:{port}/"
        should_open = self.config.auto_open if open_browser is None else open_browser
        if should_open:
            if self.config.launch_electron and self._can_launch_electron():
                self._launch_electron()
            else:
                webbrowser.open(self._url)
        return self._url

    def stop(self) -> None:
        if self._electron and self._electron.poll() is None:
            self._electron.terminate()
            try:
                self._electron.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._electron.kill()
        self._electron = None
        if self._uvicorn is not None:
            self._uvicorn.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._uvicorn = None

    def build_behaviour_payload(self, data: BehaviourData) -> dict[str, Any]:
        payload = Behaviour._default_payload(data)
        avatar = data.avatar
        if isinstance(avatar, dict):
            base = (
                avatar.get("base")
                or avatar.get("expression")
                or avatar.get("avatar")
                or "normal"
            )
            raw_overlays = avatar.get("overlays", [])
            overlays = (
                [str(item) for item in raw_overlays if item]
                if isinstance(raw_overlays, (list, tuple))
                else []
            )
            duration_ms = _nonnegative_int(
                avatar.get("duration_ms"),
                default=2400,
            )
            interrupt = bool(avatar.get("interrupt", False))
            motion = data.motion or avatar.get("motion")
            priority = _finite_int(avatar.get("priority"), data.priority)
        else:
            base = str(avatar or "normal")
            overlays = []
            duration_ms = 2400
            interrupt = False
            motion = data.motion
            priority = data.priority

        # `avatar` is the agent-facing shape. The renderer consumes this
        # normalized presentation shape so expression generation can evolve
        # without coupling it to pixi-live2d-display.
        payload.update(
            {
                "base": str(base),
                "overlays": overlays,
                "duration_ms": duration_ms,
                "interrupt": interrupt,
                "motion": str(motion) if motion else None,
                "priority": priority,
            }
        )
        audio_id = ""
        audio_url = ""
        if data.voice:
            voice_path = Path(data.voice).expanduser().resolve()
            if voice_path.is_file():
                audio_id = self.register_audio(voice_path)
                audio_url = (
                    f"/media/audio/{audio_id}?token={quote(self._token)}"
                )

        payload["audio_id"] = audio_id
        payload["audio_url"] = audio_url
        return payload

    def accept_frontend_event(
        self,
        event: FrontendEvent,
        *,
        client_id: str,
    ) -> None:
        if self.desktop_channel is None:
            raise RuntimeError("Desktop channel is not connected to MessageBus")
        self.desktop_channel.accept_event(event, client_id=client_id)

    async def process_audio(
        self,
        content: bytes,
        metadata: dict[str, Any],
        *,
        source_event: FrontendEvent,
        client_id: str,
    ) -> FrontendEvent:
        if not content:
            raise ValueError("audio message is empty")
        mime_type = str(metadata.get("mime_type") or "audio/webm")
        suffix = _audio_suffix(mime_type)
        audio_id = str(metadata.get("audio_id") or uuid4())
        safe_id = "".join(ch for ch in audio_id if ch.isalnum() or ch in "-_")
        if not safe_id:
            safe_id = str(uuid4())
        path = self.media_dir / f"{safe_id}{suffix}"
        await asyncio.to_thread(path.write_bytes, content)
        self._audio[safe_id] = path

        self.frontend_bus.publish_event(
            "input.transcribing",
            {"audio_id": safe_id},
            trace_id=source_event.trace_id,
            session_id=source_event.session_id,
            target_client_id=client_id,
        )
        transcript = await self.asr.transcribe(path)
        return FrontendEvent(
            type="input.audio",
            event_id=source_event.event_id,
            trace_id=source_event.trace_id,
            session_id=source_event.session_id,
            payload={
                "audio_id": safe_id,
                "path": str(path),
                "mime_type": mime_type,
                "size": len(content),
                "duration_ms": int(metadata.get("duration_ms") or 0),
                "transcript": transcript,
                "user_id": metadata.get("user_id", "desktop-user"),
            },
        )

    def register_audio(self, path: Path) -> str:
        audio_id = str(uuid4())
        self._audio[audio_id] = path.resolve()
        return audio_id

    def resolve_audio(self, audio_id: str) -> Path | None:
        path = self._audio.get(audio_id)
        return path if path and path.is_file() else None

    def validate_token(self, token: str) -> None:
        if not secrets.compare_digest(token, self._token):
            raise HTTPException(401, "Invalid desktop token")

    def client_config(self) -> dict[str, Any]:
        expressions = sorted(
            path.name for path in self.config.model_dir.glob("*.exp3.json")
        )
        motions = sorted(
            path.name for path in self.config.model_dir.glob("*.motion3.json")
        )
        texture_sizes = []
        try:
            import json

            model = json.loads(
                (self.config.model_dir / self.config.model_file).read_text(
                    encoding="utf-8"
                )
            )
            for name in model.get("FileReferences", {}).get("Textures", []):
                size = _png_size(self.config.model_dir / name)
                if size:
                    texture_sizes.append(
                        {"file": name, "width": size[0], "height": size[1]}
                    )
        except (OSError, ValueError):
            texture_sizes = []
        return {
            "token": self._token,
            "model_url": (
                "/live2d-model/" + quote(self.config.model_file)
            ),
            "model_name": self.config.model_file,
            "expressions": expressions,
            "motions": motions,
            "textures": texture_sizes,
            "expression_map": EXPRESSION_MAP,
            "touch_cooldown_ms": self.config.touch_cooldown_ms,
            "persistent_parameters": self.config.persistent_parameters,
            "asr_enabled": self.asr.enabled,
            "max_audio_bytes": self.config.max_audio_bytes,
        }

    def vendor_asset(self, asset_name: str) -> Path | None:
        candidates = {
            "pixi.min.js": [
                self.desktop_dir / "node_modules/pixi.js/dist/browser/pixi.min.js",
                self.desktop_dir / "node_modules/pixi.js/dist/pixi.min.js",
            ],
            "pixi-unsafe-eval.min.js": [
                self.desktop_dir
                / "node_modules/@pixi/unsafe-eval/dist/browser/unsafe-eval.min.js",
                self.desktop_dir
                / "node_modules/@pixi/unsafe-eval/dist/unsafe-eval.min.js",
            ],
            "live2d.min.js": [
                self.desktop_dir
                / "node_modules/pixi-live2d-display/dist/cubism4.min.js",
                self.desktop_dir
                / "node_modules/pixi-live2d-display/dist/index.min.js",
            ],
            "live2dcubismcore.min.js": [
                self.desktop_dir / "vendor/live2dcubismcore.min.js",
            ],
        }
        asset_candidates = list(candidates.get(asset_name, []))
        if asset_name == "live2dcubismcore.min.js":
            asset_candidates.extend(
                sorted(
                    self.desktop_dir.glob(
                        "vendor/CubismSdkForWeb-*/Core/live2dcubismcore.min.js"
                    ),
                    reverse=True,
                )
            )
        for path in asset_candidates:
            if path.is_file():
                return path
        return None

    def _can_launch_electron(self) -> bool:
        return (
            (self.desktop_dir / "main.js").is_file()
            and (
                self.desktop_dir / "node_modules/electron/dist/electron.exe"
            ).is_file()
        )

    def _launch_electron(self) -> None:
        electron = self.desktop_dir / "node_modules/electron/dist/electron.exe"
        command = [str(electron), ".", f"--server-url={self._url}"]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._electron = subprocess.Popen(
            command,
            cwd=self.desktop_dir,
            creationflags=flags,
        )


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _audio_suffix(mime_type: str) -> str:
    lowered = mime_type.lower()
    if "ogg" in lowered:
        return ".ogg"
    if "wav" in lowered:
        return ".wav"
    if "mpeg" in lowered or "mp3" in lowered:
        return ".mp3"
    return mimetypes.guess_extension(lowered.split(";", 1)[0]) or ".webm"


def _finite_int(value: Any, default: int = 0) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return int(numeric) if math.isfinite(numeric) else default


def _nonnegative_int(value: Any, default: int = 0) -> int:
    return max(0, _finite_int(value, default))


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as file:
            header = file.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return (
        int.from_bytes(header[16:20], "big"),
        int.from_bytes(header[20:24], "big"),
    )
