from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from behaviour.avatar.live2d_web import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_MODEL_DIR,
    DEFAULT_MODEL_FILE,
    DEFAULT_PORT,
    Live2DWebConfig,
    Live2DWebServer,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the manual Live2D web loader.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = Live2DWebServer(
        Live2DWebConfig(
            enabled=True,
            auto_open=not args.no_browser,
            host=args.host,
            port=args.port,
            model_dir=DEFAULT_MODEL_DIR,
            model_file=DEFAULT_MODEL_FILE,
            persistent_parameters={"Param221": 1.0},
        )
    )
    url = server.start()
    print(f"Live2D web page: {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
