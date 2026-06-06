import argparse
import base64
import os
import threading
import time
from pathlib import Path

import dashscope
from dashscope.audio.qwen_tts_realtime import (
    AudioFormat,
    QwenTtsRealtime,
    QwenTtsRealtimeCallback,
)


DEFAULT_MODEL = "qwen3-tts-flash-realtime"
DEFAULT_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
DEFAULT_VOICE = "Chelsie"


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
            }

    def _close_current_file(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


def init_dashscope_api_key() -> None:
    api_key = ""
    if not api_key:
        raise RuntimeError("Please set environment variable DASHSCOPE_API_KEY first.")
    dashscope.api_key = api_key


def build_output_path(output_dir: Path, index: int) -> Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return output_dir / f"qwentts_{timestamp}_{index:03d}.mp3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test qwentts mp3 generation delay.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--output-dir", default="test/voice_outputs")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--bit-rate", type=int, default=128)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_dashscope_api_key()

    callback = VoiceDelayCallback()
    qwen_tts_realtime = QwenTtsRealtime(
        model=args.model,
        callback=callback,
        url=args.url,
    )

    print("connecting qwentts service ...")
    qwen_tts_realtime.connect()
    qwen_tts_realtime.update_session(
        voice=args.voice,
        response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
        audio_format="mp3",
        sample_rate=args.sample_rate,
        bit_rate=args.bit_rate,
        mode="commit",
    )

    output_dir = Path(args.output_dir)
    print("enter text to synthesize. empty input exits.")

    index = 1
    try:
        while True:
            text = input("text> ").strip()
            if not text:
                break

            output_path = build_output_path(output_dir, index)
            callback.start_request(output_path)
            qwen_tts_realtime.append_text(text)
            qwen_tts_realtime.commit()

            result = callback.wait_for_response(args.timeout)
            first_audio = result["first_audio_delay_ms"]
            first_audio_text = (
                f"{first_audio:.2f} ms" if first_audio is not None else "no audio"
            )
            status = "done" if result["finished"] else "timeout"
            print(
                f"[{status}] first_audio={first_audio_text}, "
                f"total={result['total_delay_ms']:.2f} ms, "
                f"bytes={result['audio_bytes']}, file={result['output_path']}"
            )
            index += 1
    finally:
        qwen_tts_realtime.finish()
        time.sleep(0.2)
        qwen_tts_realtime.close()


if __name__ == "__main__":
    main()
