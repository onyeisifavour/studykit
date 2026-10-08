import { app, BrowserWindow, dialog, ipcMain } from 'electron';
import { spawn, spawnSync, ChildProcess } from 'child_process';
import { userInfo } from 'os';
import * as path from 'path';
import * as fs from 'fs';

let mainWindow: BrowserWindow | null = null;
let sidecar: ChildProcess | null = null;
let apiUrl = '';
let apiChild: ChildProcess | null = null;
let sidecarStarting: Promise<string> | null = null;

// The sidecar's own output is the only record of why it failed to start. When
// StudyKit is launched from a .desktop entry there is no terminal attached, so
// that output is written here instead of being lost.
let sidecarLogPath = '';
let lastSidecarError = '';

function sidecarLog(message: string): void {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  process.stdout.write(line);
  if (!sidecarLogPath) return;
  try {
    fs.appendFileSync(sidecarLogPath, line);
  } catch {
    /* logging must never break startup */
  }
}

const DEV_URL = process.env.VITE_DEV_SERVER_URL || '';

function repoRoot(): string {
  return path.resolve(app.getAppPath(), '..');
}

function pythonBin(): string {
  if (process.env.STUDYKIT_PYTHON) return process.env.STUDYKIT_PYTHON;
  return path.join(repoRoot(), '.venv', 'bin', 'python');
}

function killSidecar(p: ChildProcess | null): void {
  if (!p) return;
  const pid = p.pid;
  try {
    p.kill('SIGTERM');
  } catch {
    /* already gone */
  }
  if (pid && p.exitCode === null && p.signalCode === null) {
    const killer = setTimeout(() => {
      try {
        process.kill(pid, 'SIGKILL');
      } catch {
        /* already gone */
      }
    }, 3000);
    killer.unref();
  }
}

function cleanupOrphanSidecars(): void {
  try {
    const out = spawnSync('pgrep', ['-f', 'python -m main_app.sidecar'], {
      encoding: 'utf8',
    });
    if (out.status !== 0 || !out.stdout.trim()) return;
    for (const pidStr of out.stdout.trim().split(/\s+/)) {
      const pid = Number(pidStr);
      if (!Number.isInteger(pid) || pid <= 1) continue;
      try {
        const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
        const rest = stat.slice(stat.lastIndexOf(')') + 2).split(' ');
        const ppid = Number(rest[1]);
        const parentComm = fs
          .readFileSync(`/proc/${ppid}/comm`, 'utf8')
          .trim();
        if (parentComm === 'electron') continue; // owned by a live StudyKit instance
        if (fs.readlinkSync(`/proc/${pid}/cwd`) !== repoRoot()) continue;
        try {
          process.kill(pid, 'SIGTERM');
        } catch {
          /* already gone */
        }
      } catch {
        /* process vanished mid-scan */
      }
    }
  } catch {
    /* pgrep unavailable — skip cleanup */
  }
}

function startSidecar(): Promise<string> {
  if (sidecarStarting) return sidecarStarting;
  if (!sidecarLogPath) {
    try {
      sidecarLogPath = path.join(app.getPath('userData'), 'sidecar.log');
    } catch {
      sidecarLogPath = path.join(repoRoot(), 'sidecar.log');
    }
  }
  sidecarStarting = new Promise<string>((resolve, reject) => {
    const bin = pythonBin();
    lastSidecarError = '';
    sidecarLog(
      `--- spawn attempt: ${bin} -m main_app.sidecar (cwd=${repoRoot()}) ` +
        `binExists=${fs.existsSync(bin)}`,
    );
    const child = spawn(bin, ['-m', 'main_app.sidecar'], {
      cwd: repoRoot(),
      env: { ...process.env },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    sidecar = child;

    let settled = false;
    const fail = (reason: string, err?: unknown) => {
      lastSidecarError = err ? `${reason}: ${err instanceof Error ? err.message : String(err)}` : reason;
      sidecarLog(`FAILED — ${lastSidecarError}`);
    };

    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        sidecarStarting = null;
        child.kill('SIGTERM');
        fail('Sidecar startup timed out after 20s (no STUDYKIT_PORT line)');
        reject(new Error('Sidecar startup timed out'));
      }
    }, 20000);

    child.stdout?.on('data', (buf: Buffer) => {
      const text = buf.toString();
      sidecarLog(`stdout: ${text.replace(/\n$/, '')}`);
      const match = text.match(/STUDYKIT_PORT=(\d+)/);
      if (match && !settled) {
        settled = true;
        clearTimeout(timer);
        sidecarStarting = null;
        apiUrl = `http://127.0.0.1:${match[1]}`;
        apiChild = child;
        sidecarLog(`ready on ${apiUrl}`);
        resolve(apiUrl);
      }
    });

    child.stderr?.on('data', (buf: Buffer) =>
      sidecarLog(`stderr: ${buf.toString().replace(/\n$/, '')}`),
    );

    child.on('exit', (code, signal) => {
      if (sidecar === child) sidecar = null;
      if (child === apiChild) {
        apiChild = null;
        apiUrl = ''; // this was the active sidecar — next get-url restarts it
        sidecarLog(`active sidecar exited (code=${code} signal=${signal}) — will restart on next request`);
      }
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        sidecarStarting = null;
        fail(`Sidecar exited before startup completed (code=${code} signal=${signal})`);
        reject(new Error(`Sidecar exited with code ${code}`));
      }
    });

    child.on('error', (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        sidecarStarting = null;
        fail('Sidecar process could not be started', err);
        reject(err);
      }
    });
  });
  return sidecarStarting;
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

  // Simulation errors surface in the renderer and inside the sandboxed sim
  // iframe. Without this they go to a devtools window nobody has open, which is
  // why a missing three.js used to show up as a silently blank canvas.
  // Signature: (event, level, message, line, sourceId) — level 2 is error, 1 warning.
  mainWindow.webContents.on(
    'console-message',
    (_event, level: number, message: string, line: number, sourceId: string) => {
      if (level <= 1) return;
      const where = sourceId ? ` (${sourceId}:${line})` : '';
      sidecarLog(`renderer ${level === 2 ? 'error' : 'warning'}: ${message}${where}`);
    },
  );
  mainWindow.webContents.on('did-fail-load', (_event, code, description, url) => {
    sidecarLog(`renderer load failed [${code}] ${description} — ${url}`);
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
  cleanupOrphanSidecars();
  ipcMain.handle('sidecar:get-url', async () => {
    if (!apiUrl) {
      try {
        await startSidecar();
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        console.error('[studykit] failed to (re)start sidecar:', reason);
        sidecarLog(`get-url giving up — ${reason} (${lastSidecarError || 'no detail'})`);
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
    sidecarLog(`startup gave up — ${lastSidecarError || 'no detail'}`);
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
  killSidecar(apiChild);
  killSidecar(sidecar);
});
