# YourApp — Production & Distribution Strategy

## Overview

YourApp ships as a **single installer file** per platform. The user double-clicks,
clicks through a standard install wizard, and everything — server, daemon, Electron UI,
system services — is set up automatically. No Python, no Node.js, no terminal required.

---

## What Ships to the User

| Platform | File | Size (est.) |
|---|---|---|
| Windows | `yourapp-setup.exe` | ~180MB |
| macOS | `yourapp.dmg` | ~170MB |
| Linux | `yourapp.AppImage` | ~160MB |

Everything is bundled inside — Python runtime, all dependencies, ML models, assets.

---

## The 3 Processes in Production

```
yourapp-setup.exe unpacks:
│
├── [1] Electron App          ← UI, registered to start on user login
├── [2] Server (Python)       ← registered as system service, starts on boot
└── [3] Voice Daemon (Python) ← registered as system service, starts on boot
```

User never manually starts any of these. Installer handles registration.
On reboot everything is alive before the user even logs in.

---

## Bundle Structure

```
yourapp/                          ← what electron-builder packages
│
├── electron/                     ← Electron source
│   ├── main.js                   ← spawns server + daemon, health polling
│   ├── preload.js
│   └── renderer/                 ← UI
│
├── server/                       ← FastAPI backend
│   ├── main.py
│   ├── stt.py                    ← Groq STT
│   ├── rag.py
│   ├── llm.py
│   └── tts.py
│
├── daemon/                       ← Voice daemon
│   ├── main.py
│   ├── wake_word.py
│   ├── vad.py
│   ├── audio_stream.py
│   └── playback.py
│
├── python-embed/                 ← Embedded Python runtime (NOT system Python)
│   ├── python.exe                ← Windows
│   ├── python3                   ← macOS / Linux
│   └── Lib/                      ← all pip dependencies pre-installed
│
├── models/                       ← ML models shipped with app
│   └── wake_word.onnx            ← openwakeword model (~5MB)
│
├── assets/
│   ├── ding.wav
│   ├── icon.ico
│   ├── icon.icns
│   └── icon.png
│
├── scripts/
│   ├── service_manager.py        ← called by installer to register services
│   ├── installer.nsh             ← Windows NSIS custom install steps
│   ├── postinstall.sh            ← macOS / Linux post-install hook
│   └── com.yourapp.*.plist       ← macOS LaunchDaemon templates
│
├── package.json
├── electron-builder.yml
└── .env.template                 ← user fills in API keys on first launch
```

---

## Build Tools

| Tool | Purpose |
|---|---|
| `electron-builder` | Packages Electron + all assets into installer |
| `PyInstaller` | Optional — compiles Python to .exe (faster startup) |
| `NSIS` | Windows installer wizard (auto-used by electron-builder) |
| `DMG Canvas` / `create-dmg` | macOS disk image (auto-used by electron-builder) |
| `AppImageTool` | Linux AppImage (auto-used by electron-builder) |

---

## electron-builder.yml

```yaml
appId: com.yourapp.assistant
productName: YourApp
copyright: Copyright © 2026 YourName

# Files to include in the app package
files:
  - electron/**
  - "!electron/node_modules/.cache"

# Extra resources bundled alongside the app
extraResources:
  - from: server/
    to: server/
  - from: daemon/
    to: daemon/
  - from: python-embed/
    to: python-embed/
  - from: models/
    to: models/
  - from: assets/
    to: assets/
  - from: scripts/
    to: scripts/

# Windows
win:
  target:
    - target: nsis
      arch: [x64]
  icon: assets/icon.ico

nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  include: scripts/installer.nsh      ← runs service registration
  runAfterFinish: true
  createDesktopShortcut: true
  createStartMenuShortcut: true

# macOS
mac:
  target:
    - target: dmg
      arch: [x64, arm64]             ← Intel + Apple Silicon
  icon: assets/icon.icns
  category: public.app-category.productivity

dmg:
  background: assets/dmg-background.png
  window:
    width: 540
    height: 380

# Linux
linux:
  target:
    - target: AppImage
      arch: [x64]
  icon: assets/icon.png
  category: Utility

# Publish (auto-update)
publish:
  provider: github
  owner: yourname
  repo: yourapp
```

---

## Embedded Python Setup

User machines may not have Python — or may have the wrong version.
We ship our own Python runtime so the app is 100% self-contained.

```bash
# ── Windows ──────────────────────────────────────────────
# 1. Download embeddable package from python.org
#    python.org/downloads/windows → "Windows embeddable package (64-bit)"
# 2. Unzip to yourapp/python-embed/
# 3. Install dependencies into it:

./python-embed/python.exe -m pip install \
  fastapi uvicorn groq openai-whisper \
  pvporcupine openwakeword sounddevice \
  numpy python-dotenv requests websockets \
  silero-vad

# ── macOS ─────────────────────────────────────────────────
# Use python-build-standalone (best for bundling):
# github.com/indygreg/python-build-standalone
# Download the macOS universal2 build, unpack to python-embed/

# ── Linux ─────────────────────────────────────────────────
# Same — python-build-standalone linux x86_64 build
# or use pyenv to build a relocatable Python
```

---

## Electron — Spawning Python at Runtime

```js
// electron/main.js

const path  = require('path')
const { spawn } = require('child_process')

// Always use bundled Python — never system Python
const pythonBin = path.join(
  process.resourcesPath,
  'python-embed',
  process.platform === 'win32' ? 'python.exe' : 'python3'
)

const serverScript = path.join(process.resourcesPath, 'server', 'main.py')
const daemonScript = path.join(process.resourcesPath, 'daemon', 'main.py')

function spawnProcess(script, name) {
  const proc = spawn(pythonBin, [script], {
    detached: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONPATH: path.join(process.resourcesPath),
      YOURAPP_ROOT: process.resourcesPath,
    }
  })

  proc.stdout.on('data', d => console.log(`[${name}]`, d.toString()))
  proc.stderr.on('data', d => console.error(`[${name}]`, d.toString()))
  proc.unref()   // don't block Electron from closing
  return proc
}

// Poll /health until server is ready, then show window
async function waitForServer(retries = 20) {
  for (let i = 0; i < retries; i++) {
    try {
      await fetch('http://localhost:8000/health')
      return true
    } catch {
      await new Promise(r => setTimeout(r, 500))
    }
  }
  return false
}

app.whenReady().then(async () => {
  spawnProcess(serverScript, 'server')
  spawnProcess(daemonScript, 'daemon')

  const ready = await waitForServer()
  if (!ready) {
    dialog.showErrorBox('YourApp', 'Server failed to start. Please reinstall.')
    app.quit()
    return
  }

  createWindow()
})
```

---

## Installer — Service Registration

### Windows (NSIS hook)

```nsis
; scripts/installer.nsh
; Runs after files are copied — registers services

!macro customInstall
  ; Register server as Windows Service
  ExecWait '"$INSTDIR\python-embed\python.exe" \
            "$INSTDIR\scripts\service_manager.py" install'

  ; Add Electron to startup registry
  WriteRegStr HKCU \
    "Software\Microsoft\Windows\CurrentVersion\Run" \
    "YourApp" "$INSTDIR\YourApp.exe"
!macroend

!macro customUninstall
  ExecWait '"$INSTDIR\python-embed\python.exe" \
            "$INSTDIR\scripts\service_manager.py" uninstall'

  DeleteRegValue HKCU \
    "Software\Microsoft\Windows\CurrentVersion\Run" \
    "YourApp"
!macroend
```

### macOS / Linux (post-install script)

```bash
#!/bin/bash
# scripts/postinstall.sh

INSTALL_DIR="$(dirname "$0")/.."
PYTHON="$INSTALL_DIR/python-embed/python3"

# Register server + daemon as system services
# Register Electron as login item
"$PYTHON" "$INSTALL_DIR/scripts/service_manager.py" install

echo "YourApp services registered successfully."
```

---

## First Launch — API Key Setup

Since the server needs `GROQ_API_KEY` and other secrets, prompt on first launch:

```
First launch flow:

Electron opens
  ↓
Check if .env exists at install dir
  ↓ (no)
Show onboarding screen:
  "Enter your Groq API key to get started"
  [ ___________________________ ]  [ Continue ]
  ↓
Write to /opt/yourapp/.env  (macOS/Linux)
     or  C:\Program Files\YourApp\.env  (Windows)
  ↓
Restart server service to pick up new env
  ↓
Ready to use
```

```js
// electron — check on startup
const envPath = path.join(process.resourcesPath, '.env')
if (!fs.existsSync(envPath)) {
  showOnboardingWindow()   // collect API keys
} else {
  showMainWindow()
}
```

---

## Auto Updates

Use `electron-updater` (included with electron-builder):

```js
// electron/main.js
const { autoUpdater } = require('electron-updater')

app.whenReady().then(() => {
  autoUpdater.checkForUpdatesAndNotify()
})

autoUpdater.on('update-downloaded', () => {
  dialog.showMessageBox({
    message: 'Update ready. YourApp will restart to install it.'
  }).then(() => autoUpdater.quitAndInstall())
})
```

Updates are published to GitHub Releases automatically on each build:

```bash
# Build + publish release to GitHub
npm run build -- --publish always
```

---

## Build Pipeline (CI/CD)

```yaml
# .github/workflows/build.yml

name: Build & Release

on:
  push:
    tags: ['v*']           ← triggers on version tags like v1.0.0

jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      - run: npm ci
      - run: npm run build -- --win --publish always
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  build-macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v3
      - run: npm ci
      - run: npm run build -- --mac --publish always
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      CSC_LINK: ${{ secrets.APPLE_CERT }}          ← code signing
      CSC_KEY_PASSWORD: ${{ secrets.APPLE_CERT_PWD }}

  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: npm ci
      - run: npm run build -- --linux --publish always
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Tagging a release:
```bash
git tag v1.0.0
git push origin v1.0.0
# → CI builds all 3 platforms and uploads to GitHub Releases automatically
```

---

## Code Signing (Required for Trust)

Without signing, Windows shows "Unknown Publisher" warning and macOS blocks the app.

| Platform | What you need | Cost |
|---|---|---|
| Windows | EV Code Signing Certificate | ~$300/yr (DigiCert, Sectigo) |
| macOS | Apple Developer Account + cert | $99/yr |
| Linux | No signing needed | Free |

```bash
# macOS — notarize after signing (required for Gatekeeper)
# electron-builder handles this automatically if you set:

mac:
  notarize:
    teamId: YOUR_APPLE_TEAM_ID
```

---

## Bundle Size Breakdown

| Component | Size |
|---|---|
| Electron runtime | ~80MB |
| Python embed runtime | ~25MB |
| Python dependencies | ~40MB |
| Server + Daemon code | ~2MB |
| openwakeword model | ~5MB |
| Assets (icons, sounds) | ~2MB |
| **Total (approx)** | **~154MB** |

> Groq handles STT in the cloud so no Whisper model is bundled — saves ~40MB.

---

## Dev vs Production Paths

```python
# server/main.py — resolve paths correctly in both modes

import sys
import os

def get_root() -> str:
    if getattr(sys, 'frozen', False):
        # Running inside packaged Electron (extraResources)
        return os.environ.get('YOURAPP_ROOT', os.path.dirname(sys.executable))
    else:
        # Running in dev
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOT = get_root()
ENV_PATH = os.path.join(ROOT, '.env')
MODELS_PATH = os.path.join(ROOT, 'models')
ASSETS_PATH = os.path.join(ROOT, 'assets')
```

---

## Release Checklist

```
Before tagging a release:

  [ ] Bump version in package.json
  [ ] Update CHANGELOG.md
  [ ] Test installer on clean Windows VM (no Python installed)
  [ ] Test installer on clean macOS (check Gatekeeper)
  [ ] Test installer on Ubuntu 22.04
  [ ] Verify services register and start on reboot
  [ ] Verify lock screen voice flow works
  [ ] Verify auto-update from previous version works
  [ ] Sign and notarize macOS build
  [ ] Sign Windows build with EV cert

  git tag v1.x.x && git push origin v1.x.x
  → CI handles the rest
```

---

## Summary

```
Developer runs:   git tag v1.0.0 && git push
CI builds:        yourapp-setup.exe + yourapp.dmg + yourapp.AppImage
User downloads:   one file (~150MB)
User runs:        double-click → next → next → install
Result:           server + daemon running as system services
                  Electron auto-starts on login
                  voice assistant alive before user even logs in
```