import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('studykit', {
  getApiUrl: () => ipcRenderer.invoke('sidecar:get-url'),
  getUser: () => ipcRenderer.invoke('sidecar:get-user'),
});
