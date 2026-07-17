const { contextBridge, ipcRenderer } = require('electron');

const finitePoint = (point) => ({
  x: Number.isFinite(Number(point?.x)) ? Number(point.x) : 0,
  y: Number.isFinite(Number(point?.y)) ? Number(point.y) : 0,
});

contextBridge.exposeInMainWorld('shionDesktop', {
  getRuntime: () => ipcRenderer.invoke('desktop:get-runtime'),
  setMousePassthrough: (ignore) => ipcRenderer.send('desktop:set-mouse-passthrough', Boolean(ignore)),
  startDrag: (point) => ipcRenderer.send('desktop:drag-start', finitePoint(point)),
  moveDrag: (point) => ipcRenderer.send('desktop:drag-move', finitePoint(point)),
  endDrag: () => ipcRenderer.send('desktop:drag-end'),
  showControls: () => ipcRenderer.send('desktop:show-controls'),
  hideControls: () => ipcRenderer.send('desktop:hide-controls'),
  resizeAvatar: (size) => ipcRenderer.send('desktop:resize-avatar', {
    width: Number(size?.width),
    height: Number(size?.height),
  }),
});
