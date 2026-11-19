const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vortex', {
  getEngineConfig: () => ipcRenderer.invoke('get-engine-config'),
  selectFolder: (defaultPath) => ipcRenderer.invoke('select-folder', defaultPath),
  selectTorrentFile: () => ipcRenderer.invoke('select-torrent-file'),
  openPath: (targetPath) => ipcRenderer.invoke('open-path', targetPath),
  showInFolder: (targetPath) => ipcRenderer.invoke('show-in-folder', targetPath),
  windowMinimize: () => ipcRenderer.send('window-minimize'),
  windowMaximize: () => ipcRenderer.send('window-maximize'),
  windowClose: () => ipcRenderer.send('window-close'),
  updateTrayTooltip: (text) => ipcRenderer.send('update-tray-tooltip', text),
  notifyFinished: (payload) => ipcRenderer.send('notify-finished', payload),
  registerOsHandlers: () => ipcRenderer.invoke('register-os-handlers'),
  unregisterOsHandlers: () => ipcRenderer.invoke('unregister-os-handlers'),
  getOsHandlersStatus: () => ipcRenderer.invoke('get-os-handlers-status'),
  consumePendingExternal: () => ipcRenderer.invoke('consume-pending-external'),
  onOpenExternalTorrent: (callback) => {
    const handler = (_event, payload) => callback(payload);
    ipcRenderer.on('open-external-torrent', handler);
    return () => ipcRenderer.removeListener('open-external-torrent', handler);
  },
  onTrayAction: (callback) => {
    const handler = (_event, action) => callback(action);
    ipcRenderer.on('tray-action', handler);
    return () => ipcRenderer.removeListener('tray-action', handler);
  },
});
