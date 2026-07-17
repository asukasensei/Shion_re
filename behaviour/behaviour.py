import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from behaviour.behaviour_bus import BehaviourBus


DEFAULT_AVATAR = "normal"


@dataclass
class BehaviourData:
    avatar: dict[str, Any] | str = DEFAULT_AVATAR
    voice: str = ""
    text: str = ""
    motion: str | None = None
    priority: int = 0
    trace_id: str = ""
    session_id: str = "desktop-local"



class Behaviour:
    def __init__(
        self,
        behaviour_bus: BehaviourBus | None = None,
        payload_builder: Callable[[BehaviourData], dict[str, Any]] | None = None,
        *,
        play_local_voice: bool = True,
    ) -> None:
        self.behaviour_bus = behaviour_bus
        self.payload_builder = payload_builder or self._default_payload
        self.play_local_voice = play_local_voice

    async def play_behaviour(self, behaviour_data: BehaviourData) -> None:
        print(behaviour_data.text, flush=True)

        if self.behaviour_bus is not None:
            self.behaviour_bus.publish_event(
                "behaviour.apply",
                self.payload_builder(behaviour_data),
                trace_id=behaviour_data.trace_id,
                session_id=behaviour_data.session_id,
            )

        if not behaviour_data.voice or not self.play_local_voice:
            return

        voice_path = Path(behaviour_data.voice).expanduser().resolve()
        if not voice_path.is_file():
            raise FileNotFoundError(f"Voice file does not exist: {voice_path}")

        await asyncio.to_thread(self._play_voice, voice_path)

    @staticmethod
    def _default_payload(data: BehaviourData) -> dict[str, Any]:
        return {
            "avatar": data.avatar,
            "voice": data.voice,
            "text": data.text,
            "motion": data.motion,
            "priority": data.priority,
        }
    @staticmethod
    def _play_voice(voice_path: Path) -> None:
        escaped_path = str(voice_path).replace("'", "''")
        script = rf"""
Add-Type -AssemblyName PresentationCore
$player = New-Object System.Windows.Media.MediaPlayer
try {{
    $player.Open([Uri]::new('{escaped_path}', [UriKind]::Absolute))
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while (-not $player.NaturalDuration.HasTimeSpan) {{
        if ([DateTime]::UtcNow -ge $deadline) {{
            throw 'Timed out while loading the audio file.'
        }}
        Start-Sleep -Milliseconds 50
    }}

    $player.Play()
    $durationMs = [Math]::Ceiling(
        $player.NaturalDuration.TimeSpan.TotalMilliseconds + 250
    )
    Start-Sleep -Milliseconds $durationMs
}}
finally {{
    $player.Stop()
    $player.Close()
}}
"""

        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE
        subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Sta",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            startupinfo=startup_info,
        )
