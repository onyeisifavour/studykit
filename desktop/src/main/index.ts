import { app, BrowserWindow, dialog, ipcMain } from 'electron';
import { spawn, ChildProcess } from 'child_process';
import { userInfo } from 'os';
import * as path from 'path';

let mainWindow: BrowserWindow | null = null;
let sidecar: ChildProcess | null = null;
let apiUrl = '';

const DEV_URL = process.env.VITE_DEV_SERVER_URL || '';

function repoRoot(): string {
  return path.resolve(app.getAppPath(), '..');
}

function pythonBin(): string {
  if (process.env.STUDYKIT_PYTHON) return process.env.STUDYKIT_PYTHON;
  return path.join(repoRoot(), '.venv', 'bin', 'python');
}

function startSidecar(): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBin(), ['-m', 'main_app.sidecar'], {
      cwd: repoRoot(),
      env: { ...process.env },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    sidecar = child;

    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error('Sidecar startup timed out'));
      }
    }, 20000);

    child.stdout?.on('data', (buf: Buffer) => {
      const text = buf.toString();
      process.stdout.write(text);
      const match = text.match(/STUDYKIT_PORT=(\d+)/);
      if (match && !settled) {
        settled = true;
        clearTimeout(timer);
        apiUrl = `http://127.0.0.1:${match[1]}`;
        resolve(apiUrl);
      }
    });

    child.stderr?.on('data', (buf: Buffer) => process.stderr.write(buf.toString()));

    child.on('exit', (code) => {
      sidecar = null;
      apiUrl = ''; // stale — next get-url will restart the sidecar
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`Sidecar exited with code ${code}`));
      }
    });

    child.on('error', (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(err);
      }
    });
  });
}

async function createWindow(): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1080,
    height: 720,
    minWidth: 760,
    minHeight: 520,
    backgroundColor: '#EEF0F6',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow?.show());
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  if (DEV_URL) {
    await mainWindow.loadURL(DEV_URL);
  } else {
    await mainWindow.loadFile(path.join(__dirname, '../../renderer/index.html'));
  }
}

app.whenReady().then(async () => {
  ipcMain.handle('sidecar:get-url', async () => {
    if (!apiUrl) {
      try {
        await startSidecar();
      } catch (err) {
        console.error('[studykit] failed to (re)start sidecar:', err);
      }
    }
    return apiUrl;
  });
  ipcMain.handle('sidecar:get-user', () => ({ name: userInfo().username }));
  ipcMain.handle('sidecar:browse-folder', async () => {
    const win = BrowserWindow.getFocusedWindow() ?? mainWindow ?? undefined;
    const result = win
      ? await dialog.showOpenDialog(win, {
          title: 'Select your learning library',
          properties: ['openDirectory'],
        })
      : { canceled: true, filePaths: [] };
    if (result.canceled || result.filePaths.length === 0) return null;
    return result.filePaths[0];
  });

  try {
    await startSidecar();
  } catch (err) {
    console.error('[studykit] failed to start sidecar:', err);
  }

  await createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) void createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (sidecar) {
    sidecar.kill('SIGTERM');
    sidecar = null;
  }
});
