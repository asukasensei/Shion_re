# Shion Desktop Channel

The desktop UI is served by the Python FastAPI process and displayed in two
Electron windows:

- `AvatarWindow`: transparent Live2D overlay, click-through and touch/drag input.
- `ControlWindow`: text chat, recording and connection state.

## Setup

1. Install JavaScript dependencies:

   ```powershell
   npm.cmd install
   npm.cmd run build:renderer
   ```

2. Put the official Live2D SDK directory under `vendor`. The current runtime
   recognizes the following layout directly:

   ```text
   vendor/CubismSdkForWeb-5-r.5/Core/live2dcubismcore.min.js
   ```

   Alternatively, copy only the Core file to
   `vendor/live2dcubismcore.min.js`.

3. Configure `live2d` and optional `asr` settings using
   `config/config.example.json` as the reference.

4. Start the Python application from the repository root:

   ```powershell
   .venv\Scripts\python.exe main.py
   ```

The Python runtime starts FastAPI first and launches Electron after the gateway
is ready. Right-click or double-click the avatar to open the control window.

The renderer imports PixiJS and `pixi-live2d-display` from npm in
`renderer/renderer.js`; esbuild packages those imports into
`renderer/renderer.bundle.js`. It permits `unsafe-eval` for PixiJS 7's runtime
WebGL shader compiler. Script loading remains restricted to the local Shion
gateway; do not serve this renderer from an untrusted or public origin.

## Interaction

- A short, stationary click on the visible model sends a semantic touch event.
- Moving 6px, or slowly moving more than 3px, locks the gesture into window dragging.
- Ambiguous gestures are ignored, and touch events are rate-limited instead of replayed after reconnects.
- Transparent area: mouse input passes to the window below.
- Hold `按住说话`: sends WebM/Opus audio over the existing WebSocket.

Speech-to-text is optional. When `asr.enabled` is false, the original audio is
still attached to a unified desktop-channel message.

Model-specific parameters that must survive motions and expressions can be
declared in `live2d.persistent_parameters`. For the bundled model,
`{"Param221": 1.0}` keeps its built-in watermark toggle disabled.
