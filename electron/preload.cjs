const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('pdas', {
  platform: process.platform,
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    toggleMaximize: () => ipcRenderer.invoke('window:toggleMaximize'),
    close: () => ipcRenderer.invoke('window:close')
  },
  // Which server this client talks to. Stored per machine, so an analyst sets
  // it once rather than on every sign-in.
  settings: {
    get: () => ipcRenderer.invoke('settings:get'),
    set: (patch) => ipcRenderer.invoke('settings:set', patch)
  }
})
