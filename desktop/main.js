const { app, BrowserWindow, Menu, Notification, Tray, dialog, ipcMain, nativeTheme, shell } = require('electron');
const { spawn, execFile } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

const ROOT_DIR = path.resolve(__dirname, '..');
const ENGINE_DIR = path.join(ROOT_DIR, 'engine');
const PYTHON_EXE = path.join(ENGINE_DIR, '.venv', 'Scripts', 'python.exe');
const ENGINE_ENTRY = path.join(ENGINE_DIR, 'main.py');
const UI_INDEX = path.join(ROOT_DIR, 'ui', 'dist', 'index.html');
const ICON_ICO = path.join(__dirname, 'assets', 'icon.ico');
const ICON_PNG = path.join(__dirname, 'assets', 'icon.png');
const SCRIPTS_DIR = path.join(ROOT_DIR, 'scripts');

const IS_SMOKE_TEST = process.env.NEXO_SMOKE_TEST === '1';

let mainWindow = null;
let tray = null;
let engineProc = null;
let enginePort = 19742;
let engineToken = '';
let isQuitting = false;
let shutdownDone = false;
let pendingExternal = [];

nativeTheme.themeSource = 'dark';

function parseExternalArg(argv) {
  for (const raw of argv) {
    if (!raw || typeof raw !== 'string') continue;
    const arg = raw.trim().replace(/^"|"$/g, '');
    if (arg.toLowerCase().startsWith('magnet:?')) {
      return { kind: 'magnet', uri: arg };
    }
    if (arg.toLowerCase().endsWith('.torrent') && fs.existsSync(arg)) {
      try {
        const buf = fs.readFileSync(arg);
        return {
          kind: 'file',
          path: arg,
          name: path.basename(arg),
          base64: buf.toString('base64'),
        };
      } catch {
        // ignora erro de leitura
      }
    }
  }
  return null;
}

const initialExternal = parseExternalArg(process.argv.slice(1));
if (initialExternal) {
  pendingExternal.push(initialExternal);
}

const gotLock = IS_SMOKE_TEST ? true : app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  process.exit(0);
}

app.on('second-instance', (_event, argv) => {
  const payload = parseExternalArg(argv.slice(1));
  if (payload) {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('open-external-torrent', payload);
    } else {
      pendingExternal.push(payload);
    }
  }
  focusMainWindow();
});

function focusMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (!mainWindow.isVisible()) mainWindow.show();
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.focus();
}

function checkPortFree(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', () => resolve(false));
    srv.listen(port, '127.0.0.1', () => {
      srv.close(() => resolve(true));
    });
  });
}

function getEphemeralPort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address();
      srv.close(() => resolve(addr.port));
    });
  });
}

async function resolveEnginePort() {
  if (!IS_SMOKE_TEST && (await checkPortFree(19742))) {
    return 19742;
  }
  return getEphemeralPort();
}

function httpGetJson(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { headers, timeout: 1500 }, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(body));
          } catch {
            resolve({});
          }
        } else {
          reject(new Error(`HTTP ${res.statusCode}`));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => req.destroy(new Error('timeout')));
  });
}

function httpPost(url, headers = {}) {
  return new Promise((resolve) => {
    const parsed = new URL(url);
    const req = http.request(
      {
        hostname: parsed.hostname,
        port: parsed.port,
        path: parsed.pathname,
        method: 'POST',
        headers,
        timeout: 1500,
      },
      (res) => {
        res.resume();
        resolve(res.statusCode || 0);
      }
    );
    req.on('error', () => resolve(0));
    req.on('timeout', () => {
      req.destroy();
      resolve(0);
    });
    req.end();
  });
}

async function startEngine() {
  if (!fs.existsSync(PYTHON_EXE)) {
    throw new Error(`Python venv não encontrado em: ${PYTHON_EXE}`);
  }
  enginePort = await resolveEnginePort();
  engineToken = crypto.randomBytes(24).toString('hex');

  engineProc = spawn(
    PYTHON_EXE,
    [
      ENGINE_ENTRY,
      '--host', '127.0.0.1',
      '--port', String(enginePort),
      '--token', engineToken,
      '--parent-pid', String(process.pid),
    ],
    {
      cwd: ENGINE_DIR,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );

  let stderrBuf = '';
  engineProc.stderr.on('data', (chunk) => {
    stderrBuf += chunk.toString();
    if (stderrBuf.length > 4000) stderrBuf = stderrBuf.slice(-4000);
  });

  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (engineProc.exitCode !== null) {
      throw new Error(`Motor encerrou prematuramente (código ${engineProc.exitCode}): ${stderrBuf}`);
    }
    try {
      const h = await httpGetJson(`http://127.0.0.1:${enginePort}/health`);
      if (h && h.status === 'ok') return;
    } catch {
      await new Promise((r) => setTimeout(r, 150));
    }
  }
  throw new Error('Timeout aguardando inicialização do motor libtorrent.');
}

async function stopEngineGracefully() {
  if (shutdownDone || !engineProc || engineProc.exitCode !== null) {
    shutdownDone = true;
    return;
  }
  shutdownDone = true;

  await httpPost(`http://127.0.0.1:${enginePort}/api/system/shutdown`, {
    'X-Nexo-Token': engineToken,
  });

  const waitStart = Date.now();
  while (Date.now() - waitStart < 4000) {
    if (!engineProc || engineProc.exitCode !== null) return;
    await new Promise((r) => setTimeout(r, 100));
  }

  try {
    engineProc.kill('SIGTERM');
  } catch {
    // ignora
  }
  await new Promise((r) => setTimeout(r, 400));
  if (engineProc && engineProc.exitCode === null && process.platform === 'win32') {
    execFile('taskkill', ['/PID', String(engineProc.pid), '/T', '/F'], () => {});
  }
}

async function shouldMinimizeToTray() {
  try {
    const cfg = await httpGetJson(`http://127.0.0.1:${enginePort}/api/config`, {
      'X-Nexo-Token': engineToken,
    });
    return Boolean(cfg.minimize_to_tray);
  } catch {
    return true;
  }
}

function createTray() {
  if (IS_SMOKE_TEST) return;
  const iconPath = fs.existsSync(ICON_PNG) ? ICON_PNG : ICON_ICO;
  tray = new Tray(iconPath);
  tray.setToolTip('Nexo Torrent');
  tray.on('click', focusMainWindow);
  const menu = Menu.buildFromTemplate([
    { label: 'Abrir Nexo Torrent', click: focusMainWindow },
    { type: 'separator' },
    {
      label: 'Retomar todos',
      click: () => mainWindow?.webContents.send('tray-action', 'resume_all'),
    },
    {
      label: 'Pausar todos',
      click: () => mainWindow?.webContents.send('tray-action', 'pause_all'),
    },
    { type: 'separator' },
    {
      label: 'Sair',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setContextMenu(menu);
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1220,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    frame: false,
    backgroundColor: '#080909',
    show: !IS_SMOKE_TEST,
    icon: fs.existsSync(ICON_ICO) ? ICON_ICO : undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.on('close', async (e) => {
    if (isQuitting || IS_SMOKE_TEST) return;
    e.preventDefault();
    const minTray = await shouldMinimizeToTray();
    if (minTray) {
      mainWindow.hide();
    } else {
      isQuitting = true;
      app.quit();
    }
  });

  const devUrl = process.env.NEXO_DEV_URL;
  if (devUrl) {
    mainWindow.loadURL(devUrl);
  } else {
    mainWindow.loadFile(UI_INDEX);
  }

  if (IS_SMOKE_TEST) {
    const errors = [];
    mainWindow.webContents.on('console-message', (details) => {
      if (details && details.level >= 3) errors.push(details.message);
    });
    mainWindow.webContents.on('did-fail-load', (_e, code, desc) => {
      errors.push(`did-fail-load ${code}: ${desc}`);
    });
    mainWindow.webContents.once('did-finish-load', async () => {
      await new Promise((r) => setTimeout(r, 1500));
      try {
        await httpGetJson(`http://127.0.0.1:${enginePort}/api/state`, {
          'X-Nexo-Token': engineToken,
        });
        if (errors.length > 0) {
          console.error('SMOKE_CONSOLE_ERRORS:', errors.join('; '));
          isQuitting = true;
          await stopEngineGracefully();
          app.exit(1);
          return;
        }
        console.log('SMOKE_TEST_OK', `port=${enginePort}`);
        isQuitting = true;
        await stopEngineGracefully();
        app.exit(0);
      } catch (err) {
        console.error('SMOKE_API_FAIL:', err.message);
        isQuitting = true;
        await stopEngineGracefully();
        app.exit(1);
      }
    });
  }
}

function runPowerShellFile(scriptName) {
  return new Promise((resolve) => {
    const scriptPath = path.join(SCRIPTS_DIR, scriptName);
    execFile(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', scriptPath],
      { windowsHide: true },
      (err, stdout, stderr) => {
        if (err) {
          resolve({ ok: false, message: (stderr || err.message || '').trim() || 'Falha ao executar script.' });
        } else {
          resolve({ ok: true, message: stdout.trim() || 'Operação concluída.' });
        }
      }
    );
  });
}

function queryRegExists(keyPath) {
  return new Promise((resolve) => {
    execFile('reg.exe', ['query', keyPath], { windowsHide: true }, (err, stdout) => {
      resolve(!err && stdout.includes('NexoTorrent'));
    });
  });
}

function setupIpc() {
  ipcMain.handle('get-engine-config', () => ({
    baseUrl: `http://127.0.0.1:${enginePort}`,
    wsUrl: `ws://127.0.0.1:${enginePort}/ws`,
    token: engineToken,
  }));

  ipcMain.handle('consume-pending-external', () => {
    const items = [...pendingExternal];
    pendingExternal = [];
    return items;
  });

  ipcMain.handle('select-folder', async (_e, defaultPath) => {
    const res = await dialog.showOpenDialog(mainWindow, {
      title: 'Selecionar pasta de destino',
      defaultPath: defaultPath && fs.existsSync(defaultPath) ? defaultPath : undefined,
      properties: ['openDirectory', 'createDirectory'],
    });
    if (res.canceled || res.filePaths.length === 0) return null;
    return res.filePaths[0];
  });

  ipcMain.handle('select-torrent-file', async () => {
    const res = await dialog.showOpenDialog(mainWindow, {
      title: 'Selecionar arquivo .torrent',
      filters: [{ name: 'Arquivos Torrent', extensions: ['torrent'] }],
      properties: ['openFile'],
    });
    if (res.canceled || res.filePaths.length === 0) return null;
    const fp = res.filePaths[0];
    const buf = fs.readFileSync(fp);
    return { path: fp, name: path.basename(fp), base64: buf.toString('base64') };
  });

  ipcMain.handle('open-path', async (_e, targetPath) => {
    if (targetPath && fs.existsSync(targetPath)) {
      await shell.openPath(targetPath);
    }
  });

  ipcMain.handle('show-in-folder', async (_e, targetPath) => {
    if (targetPath && fs.existsSync(targetPath)) {
      shell.showItemInFolder(targetPath);
    }
  });

  ipcMain.handle('open-external', async (_e, targetUrl) => {
    try {
      const parsed = new URL(String(targetUrl || ''));
      if (parsed.protocol === 'https:') {
        await shell.openExternal(parsed.toString());
        return true;
      }
    } catch {
      // ignora URL invalida
    }
    return false;
  });

  ipcMain.on('window-minimize', () => mainWindow?.minimize());
  ipcMain.on('window-maximize', () => {
    if (!mainWindow) return;
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  });
  ipcMain.on('window-close', () => mainWindow?.close());

  ipcMain.on('update-tray-tooltip', (_e, text) => {
    if (tray && !tray.isDestroyed()) {
      tray.setToolTip(String(text || 'Nexo Torrent').slice(0, 120));
    }
  });

  ipcMain.on('notify-finished', (_e, payload) => {
    if (IS_SMOKE_TEST) return;
    if (Notification.isSupported()) {
      const n = new Notification({
        title: 'Download concluído',
        body: payload?.name || 'Torrent finalizado',
        icon: fs.existsSync(ICON_PNG) ? ICON_PNG : undefined,
      });
      n.on('click', () => {
        focusMainWindow();
        if (payload?.final_save_path && fs.existsSync(payload.final_save_path)) {
          shell.openPath(payload.final_save_path);
        }
      });
      n.show();
    }
  });

  ipcMain.handle('register-os-handlers', () => runPowerShellFile('register-handlers.ps1'));
  ipcMain.handle('unregister-os-handlers', () => runPowerShellFile('unregister-handlers.ps1'));
  ipcMain.handle('get-os-handlers-status', async () => {
    const [magnet, torrent] = await Promise.all([
      queryRegExists('HKCU\\Software\\Classes\\magnet\\shell\\open\\command'),
      queryRegExists('HKCU\\Software\\Classes\\.torrent'),
    ]);
    return { magnet, torrent };
  });
}

app.whenReady().then(async () => {
  app.setAppUserModelId('com.nexotorrent.app');
  setupIpc();
  try {
    await startEngine();
  } catch (err) {
    if (IS_SMOKE_TEST) {
      console.error('SMOKE_ENGINE_FAIL:', err.message);
      app.exit(1);
      return;
    }
    dialog.showErrorBox('Erro ao iniciar Nexo Torrent', err.message);
    app.quit();
    return;
  }
  createTray();
  createMainWindow();
});

app.on('before-quit', async (e) => {
  if (!shutdownDone) {
    e.preventDefault();
    isQuitting = true;
    await stopEngineGracefully();
    app.quit();
  }
});

app.on('window-all-closed', () => {
  if (IS_SMOKE_TEST) {
    isQuitting = true;
    app.quit();
  }
});
