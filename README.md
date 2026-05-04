# Bicentra Desktop

AI-powered pharmacy PMS automation agent — the desktop client of the
[Bicentra](https://bicentra.ai) platform.

Bicentra Desktop watches what happens on screen, records repeatable
"flows" against your existing pharmacy software (PioneerRx, BestRx,
Liberty, Framework LTC, PrimeRx), and replays them on demand. Every
run is logged to the Bicentra dashboard with screenshots and an MP4
slideshow.

## Tech stack

- Python 3.13+
- [Flet](https://flet.dev) (Flutter-based GUI)
- `pyautogui` + `pynput` for screen capture and input
- `imageio` + `imageio-ffmpeg` for the slideshow video
- `cryptography` (Fernet) for local token storage
- `requests` for the Bicentra HTTP API
- `psutil` for hardware detection

## Run from source

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

On macOS, grant **Accessibility** and **Screen Recording** permissions
the first time you run it (System Settings → Privacy & Security).

## Build a binary

### macOS — `.app` and `.dmg`

```bash
flet build macos
# Then drag dist/Bicentra Desktop.app into a .dmg via hdiutil:
hdiutil create -volname "Bicentra Desktop" \
  -srcfolder "build/macos/Bicentra Desktop.app" \
  -ov -format UDZO "dist/Bicentra Desktop.dmg"
```

### Windows — `.exe`

```bash
flet build windows
# Output: build/windows/Bicentra Desktop.exe
```

## Configuration

`config.py`:

- `APP_VERSION` — bumped on every release.
- `DEBUG` — when `True`, the app talks to `https://beta.api.bicentra.ai`.
  When `False`, it talks to `https://api.bicentra.ai`.

Per-machine preferences (recording tier, last-used flow inputs, JWT)
live in `~/.bicentra/`.

## Layout

```
bicentra-desktop/
├── main.py             # Flet app shell + tabs (Run / Record / Manage / History / Settings)
├── api_client.py       # Bicentra HTTP API wrapper
├── auth_store.py       # Encrypted JWT storage at ~/.bicentra/session.enc
├── automation.py       # pyautogui wrappers (screenshot, click, type, scroll)
├── recorder.py         # pynput listener that turns user input into flow steps
├── video.py            # imageio slideshow MP4 builder
├── system_info.py      # CPU/RAM/platform detection + recording-tier recommender
├── settings_store.py   # ~/.bicentra/settings.json load/save
├── windows.py          # cross-platform window/app focus
└── config.py           # APP_VERSION + API URL switching
```
