import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_AVATAR = "normal"


@dataclass
class BehaviourData:
    avatar: dict[str, Any] | str = DEFAULT_AVATAR
    voice: str = ""
    text: str = ""


class Behaviour:
    async def play_behaviour(self, behaviour_data: BehaviourData) -> None:
        print(behaviour_data.text, flush=True)

        if not behaviour_data.voice:
            return

        voice_path = Path(behaviour_data.voice).expanduser().resolve()
        if not voice_path.is_file():
            raise FileNotFoundError(f"Voice file does not exist: {voice_path}")

        await asyncio.to_thread(self._play_voice, voice_path)

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
