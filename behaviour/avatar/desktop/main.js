const { app, BrowserWindow, ipcMain, screen, session } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

let avatarWindow = null;
let controlWindow = null;
let dragState = null;
let saveTimer = null;

const serverArg = process.argv.find((arg) => arg.startsWith('--server-url='));
const serverUrl = serverArg
  ? serverArg.slice('--server-url='.length)
  : process.env.SHION_SERVER_URL || 'http://127.0.0.1:8765/';

// The avatar window is normally shown without focus, so Chromium would
// otherwise reject agent-initiated TTS playback as autoplay.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

function statePath() {
  return path.join(app.getPath('userData'), 'desktop-state.json');
}

function loadState() {
  try {
    return JSON.parse(fs.readFileSync(statePath(), 'utf8'));
  } catch (_) {
    return {};
  }
}

function scheduleSaveState() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    if (!avatarWindow || avatarWindow.isDestroyed()) return;
    const state = { avatarBounds: avatarWindow.getBounds() };
    fs.mkdirSync(path.dirname(statePath()), { recursive: true });
    fs.writeFileSync(statePath(), JSON.stringify(state, null, 2), 'utf8');
  }, 250);
}

function secureWebPreferences() {
  return {
    preload: path.join(__dirname, 'preload.js'),
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    webSecurity: true,
    backgroundThrottling: false,
  };
}

function clampBounds(bounds) {
  const display = screen.getDisplayMatching(bounds);
  const area = display.workArea;
  const visibleX = Math.min(100, Math.floor(bounds.width * 0.25));
  const visibleY = Math.min(120, Math.floor(bounds.height * 0.2));
  return {
    x: Math.max(area.x - bounds.width + visibleX, Math.min(bounds.x, area.x + area.width - visibleX)),
    y: Math.max(area.y, Math.min(bounds.y, area.y + area.height - visibleY)),
    width: bounds.width,
    height: bounds.height,
  };
}

function createAvatarWindow() {
  const saved = loadState().avatarBounds;
  const primary = screen.getPrimaryDisplay().workArea;
  const initial = clampBounds(saved || {
    width: 480,
    height: 720,
    x: primary.x + primary.width - 500,
    y: primary.y + primary.height - 740,
  });
  avatarWindow = new BrowserWindow({
    ...initial,
    show: false,
    transparent: true,
    backgroundColor: '#00000000',
    frame: false,
    hasShadow: false,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: true,
    webPreferences: secureWebPreferences(),
  });
  avatarWindow.setAlwaysOnTop(true, 'floating');
  avatarWindow.loadURL(`${serverUrl}?mode=avatar`);
  avatarWindow.once('ready-to-show', () => avatarWindow.showInactive());
  avatarWindow.on('move', scheduleSaveState);
  avatarWindow.on('closed', () => {
    avatarWindow = null;
    if (!app.isQuitting) app.quit();
  });
  protectNavigation(avatarWindow);
}

function createControlWindow() {
  controlWindow = new BrowserWindow({
    width: 420,
    height: 420,
    show: false,
    transparent: true,
    backgroundColor: '#00000000',
    frame: false,
    hasShadow: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: secureWebPreferences(),
  });
  controlWindow.loadURL(`${serverUrl}?mode=control`);
  controlWindow.on('blur', () => {
    if (controlWindow && !controlWindow.webContents.isDevToolsOpened()) {
      controlWindow.hide();
    }
  });
  controlWindow.on('closed', () => { controlWindow = null; });
  protectNavigation(controlWindow);
}

function protectNavigation(win) {
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(serverUrl)) event.preventDefault();
  });
}

function showControls() {
  if (!avatarWindow || !controlWindow) return;
  const avatar = avatarWindow.getBounds();
  const panel = controlWindow.getBounds();
  const desired = clampBounds({
    ...panel,
    x: avatar.x - panel.width + 36,
    y: avatar.y + Math.max(20, avatar.height - panel.height - 60),
  });
  controlWindow.setPosition(desired.x, desired.y, false);
  controlWindow.show();
  controlWindow.focus();
}

function registerIpc() {
  ipcMain.on('desktop:set-mouse-passthrough', (event, ignore) => {
    if (!avatarWindow || event.sender !== avatarWindow.webContents) return;
    avatarWindow.setIgnoreMouseEvents(Boolean(ignore), { forward: Boolean(ignore) });
  });
  ipcMain.on('desktop:drag-start', (event, point) => {
    if (!avatarWindow || event.sender !== avatarWindow.webContents) return;
    dragState = {
      cursor: { x: Number(point.x), y: Number(point.y) },
      bounds: avatarWindow.getBounds(),
    };
  });
  ipcMain.on('desktop:drag-move', (event, point) => {
    if (!avatarWindow || event.sender !== avatarWindow.webContents || !dragState) return;
    const bounds = clampBounds({
      ...dragState.bounds,
      x: dragState.bounds.x + Number(point.x) - dragState.cursor.x,
      y: dragState.bounds.y + Number(point.y) - dragState.cursor.y,
    });
    avatarWindow.setPosition(Math.round(bounds.x), Math.round(bounds.y), false);
  });
  ipcMain.on('desktop:drag-end', () => { dragState = null; });
  ipcMain.on('desktop:show-controls', showControls);
  ipcMain.on('desktop:hide-controls', () => controlWindow && controlWindow.hide());
  ipcMain.on('desktop:resize-avatar', (event, size) => {
    if (!avatarWindow || event.sender !== avatarWindow.webContents) return;
    const width = Math.max(280, Math.min(900, Math.round(Number(size.width) || 480)));
    const height = Math.max(420, Math.min(1200, Math.round(Number(size.height) || 720)));
    const current = avatarWindow.getBounds();
    const next = clampBounds({ ...current, width, height, y: current.y + current.height - height });
    avatarWindow.setBounds(next, false);
  });
  ipcMain.handle('desktop:get-runtime', () => ({ serverUrl }));
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showControls);
  app.whenReady().then(() => {
    session.defaultSession.setPermissionRequestHandler((_contents, permission, callback) => {
      callback(permission === 'media');
    });
    registerIpc();
    createAvatarWindow();
    createControlWindow();
  });
}

app.on('before-quit', () => { app.isQuitting = true; });
app.on('window-all-closed', () => app.quit());
