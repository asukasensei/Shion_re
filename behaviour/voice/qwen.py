import argparse
import base64
import os
import threading
import time
from pathlib import Path

from behaviour.voice.tts_base import BaseTTSProvider

try:
    import dashscope
    from dashscope.audio.qwen_tts_realtime import (
        AudioFormat,
        QwenTtsRealtime,
        QwenTtsRealtimeCallback,
    )
except ModuleNotFoundError:
    dashscope = None
    AudioFormat = None
    QwenTtsRealtime = None

    class QwenTtsRealtimeCallback:
        pass


DEFAULT_MODEL = "qwen3-tts-flash-realtime"
DEFAULT_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
DEFAULT_VOICE = "Chelsie"


def ensure_dashscope_available() -> None:
    if dashscope is None or QwenTtsRealtime is None or AudioFormat is None:
        raise ImportError(
            "dashscope is required for qwen TTS. Please install dashscope first."
        )


class VoiceDelayCallback(QwenTtsRealtimeCallback):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._done_event = threading.Event()
        self._file = None
        self._output_path: Path | None = None
        self._start_time = 0.0
        self._first_audio_delay_ms: float | None = None
        self._audio_bytes = 0
        self._response_id: str | None = None
        self._error_response: dict | None = None

    def on_open(self) -> None:
        print("qwentts websocket connected.")

    def on_close(self, close_status_code, close_msg) -> None:
        self._close_current_file()
        print(f"qwentts websocket closed. code={close_status_code}, msg={close_msg}")

    def on_event(self, response: dict) -> None:
        event_type = response.get("type")

        if event_type == "session.created":
            session_id = response.get("session", {}).get("id")
            print(f"session created: {session_id}")
            return

        if event_type == "response.created":
            with self._lock:
                self._response_id = response.get("response", {}).get("id")
            return

        if event_type == "response.audio.delta":
            audio = base64.b64decode(response.get("delta", ""))
            with self._lock:
                if self._first_audio_delay_ms is None:
                    self._first_audio_delay_ms = (
                        time.perf_counter() - self._start_time
                    ) * 1000
                self._audio_bytes += len(audio)
                if self._file is not None:
                    self._file.write(audio)
            return

        if event_type == "response.done":
            self._close_current_file()
            self._done_event.set()
            return

        if event_type in {"error", "response.failed"}:
            print(f"[qwentts error] {response}")
            with self._lock:
                self._error_response = response
            self._close_current_file()
            self._done_event.set()

    def start_request(self, output_path: Path) -> None:
        self._close_current_file()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._output_path = output_path
            self._start_time = time.perf_counter()
            self._first_audio_delay_ms = None
            self._audio_bytes = 0
            self._response_id = None
            self._error_response = None
            self._done_event.clear()
            self._file = output_path.open("wb")

    def wait_for_response(self, timeout: float) -> dict:
        finished = self._done_event.wait(timeout)
        total_delay_ms = (time.perf_counter() - self._start_time) * 1000
        self._close_current_file()
        with self._lock:
            return {
                "finished": finished,
                "response_id": self._response_id,
                "output_path": self._output_path,
                "first_audio_delay_ms": self._first_audio_delay_ms,
                "total_delay_ms": total_delay_ms,
                "audio_bytes": self._audio_bytes,
                "error_response": self._error_response,
            }

    def _close_current_file(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


def init_dashscope_api_key(api_key: str | None = None) -> None:
    ensure_dashscope_available()
    api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Please set tts.api_key in config.json or environment variable DASHSCOPE_API_KEY first."
        )
    dashscope.api_key = api_key


def build_output_path(output_dir: Path, index: int) -> Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return output_dir / f"qwentts_{timestamp}_{index:03d}.mp3"


class QwenTTSProvider(BaseTTSProvider):
    def __init__(self, tts_config: dict):
        ensure_dashscope_available()
        self.model = tts_config.get("model") or DEFAULT_MODEL
        self.url = tts_config.get("url") or DEFAULT_URL
        self.voice = (
            tts_config.get("voice") or tts_config.get("character") or DEFAULT_VOICE
        )
        self.output_dir = Path(tts_config.get("output_dir") or "test/voice_outputs")
        self.timeout = float(tts_config.get("timeout", 60.0))
        self.sample_rate = int(tts_config.get("sample_rate", 24000))
        self.bit_rate = int(tts_config.get("bit_rate", 128))
        self._request_index = 0
        self._lock = threading.Lock()
        self._connected = False

        init_dashscope_api_key(tts_config.get("api_key"))
        self.callback = VoiceDelayCallback()
        self.client = QwenTtsRealtime(
            model=self.model,
            callback=self.callback,
            url=self.url,
        )
        self._connect()

    def _connect(self) -> None:
        if self._connected:
            return
        print("connecting qwentts service ...")
        self.client.connect()
        self.client.update_session(
            voice=self.voice,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            audio_format="mp3",
            sample_rate=self.sample_rate,
            bit_rate=self.bit_rate,
            mode="commit",
        )
        self._connected = True

    def get_voice(self, text: str, output_path: str | Path | None = None) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Text to synthesize cannot be empty.")

        with self._lock:
            self._request_index += 1
            voice_path = (
                Path(output_path)
                if output_path is not None
                else build_output_path(self.output_dir, self._request_index)
            )
            voice_path = voice_path.resolve()

            self.callback.start_request(voice_path)
            self.client.append_text(text)
            self.client.commit()

            result = self.callback.wait_for_response(self.timeout)
            if result["error_response"]:
                raise RuntimeError(f"Qwen TTS failed: {result['error_response']}")
            if not result["finished"]:
                raise TimeoutError(
                    f"Qwen TTS timed out after {self.timeout} seconds: {voice_path}"
                )
            if result["audio_bytes"] <= 0:
                raise RuntimeError(f"Qwen TTS returned no audio: {voice_path}")
            return str(voice_path)

    def close(self) -> None:
        if not self._connected:
            return
        try:
            self.client.finish()
            time.sleep(0.2)
        finally:
            self.client.close()
            self._connected = False

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


