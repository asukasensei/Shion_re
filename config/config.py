import json
import os
from pathlib import Path


class Config:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else Path(__file__).with_name("config.json")
        self.config: dict = {}
        self.load_config()

    def load_config(self) -> None:
        if os.path.exists(self.config_path):
            with self.config_path.open("r", encoding="utf-8") as f:
                self.config = json.load(f)


config = Config().config
