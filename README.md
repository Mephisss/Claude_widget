# claude-widget

A small floating widget that shows how much of my Claude Code session and
weekly quota I've burned through. I got tired of typing `/usage` every ten
minutes, so I made this.

It shows the same numbers as the slash command, just always visible in the
corner of the screen. If the API gets rate-limited it falls back to counting
tokens from the local JSONL session logs, so you still see something useful.

## Get it

**Windows**: grab `claude-widget.exe` from the [latest release](https://github.com/Mephisss/Claude_widget/releases/latest)
and double-click. SmartScreen will yell at you because the binary isn't
code-signed (paying $200/year for that felt silly), so click "More info" then
"Run anyway". After that it just runs.

**macOS or Linux**: no prebuilt binary yet. You'll need to build it yourself,
which takes about five minutes. Steps below.

## Run it without building

You need Python 3.10+ with Tk. On most systems that's already there.

```bash
pip install pystray pillow
python widget.py
```

If Tk is missing:
- Ubuntu/Debian: `sudo apt install python3-tk`
- macOS via Homebrew: `brew install python-tk@3.12`
- macOS python.org installer: nothing to do, it's bundled

## Building a binary

PyInstaller can't cross-compile, so do this on whichever OS you want a binary
for.

### Windows

```powershell
pip install pyinstaller pystray pillow
python build.py
```

That spits out `dist\claude-widget.exe`. Add `--console` if you want a
terminal window for debugging, or `--clean` to wipe previous builds first.

### macOS

```bash
brew install python-tk@3.12

python3 -m venv .venv
source .venv/bin/activate
pip install pyinstaller pystray pillow

python build.py
```

You get `dist/claude-widget`. Drag it to `/Applications` if you want.

The first time you double-click, macOS will refuse to open it because Apple
doesn't recognize me as a developer. Right-click it, pick Open, then Open
again on the warning. After that it remembers and just opens normally.

### Linux

```bash
sudo apt install python3-tk libappindicator3-1
python3 -m venv .venv && source .venv/bin/activate
pip install pyinstaller pystray pillow
python build.py
chmod +x dist/claude-widget
./dist/claude-widget
```

## Using it

It's a normal little window. Drag anywhere to move it, drag the corner grip
to resize. The layout changes based on size: tiny shows just two big numbers,
medium shows bars and reset times, big shows the per-bucket breakdown plus
local token totals.

Right-click for the menu. From there you can pin it on top, send it behind
other windows, change settings, re-run the credentials wizard, or quit. The
system tray icon (orange octopus thing) lets you show/hide.

Double-click the widget itself to force a refresh. It polls every 60 seconds
by default because the endpoint rate-limits aggressively, so be careful if
you crank that down.

## Settings

Everything lives in `config.json` next to the binary, or you can edit it
through the Settings dialog (right-click). The interesting knobs:

| Key | What it does |
| --- | --- |
| `theme` | `claude_code` (orange terminal vibe), `dark`, or `light` |
| `backdrop` | `solid`, `mica` (Win11), or `acrylic_experimental` |
| `font_family` | Monospace font. OS default if you leave it. |
| `width`, `height` | Size in pixels. Min 160x56. Layout switches at 280x110 and 260+ tall. |
| `alpha` | Window opacity, 0.2 to 1.0 |
| `refresh_seconds` | How often to poll the API. 60 is reasonable. |
| `tray_enabled` | Whether to show the system tray icon |
| `glitch_on_open` / `glitch_on_close` | The little VHS animation. Turn off if you hate it. |
| `credentials_path` | Force a specific path. Leave `null` to auto-detect. |

## First-run setup

When you launch it the first time, it tries to find your Claude Code
credentials in the usual places:

- `~/.claude/.credentials.json` (most setups)
- macOS Keychain (`security find-generic-password -s "Claude Code-credentials"`)
- `%APPDATA%\Claude\.credentials.json` and friends on Windows
- `$XDG_CONFIG_HOME/{claude,Claude,anthropic}/.credentials.json` on Linux

If none of those work, a tiny wizard pops up showing you all the paths it
checked. You can pick one, browse to a custom location, or skip. The wizard
never shows the token itself, only its file path. You can re-run it later
from the right-click menu if you ever change machines.

## How big is it in memory

About 40 to 55 MB resident on Windows. Most of that is Pillow and the Tk
runtime. Setting `tray_enabled: false` saves you another ~5 MB by skipping
the pystray import entirely.

## How it handles your token

The OAuth token from your credentials file gets wrapped in a class whose
`repr`, `str`, and string interpolation all return `<SecretToken redacted>`.
So if it ever ends up in an exception message or a log, it just shows that
placeholder. The original string from disk gets overwritten with `x`s after
use. All HTTP calls go over TLS, and on errors I strip the request headers
out of the raised exception so the Authorization header can't leak.

Only the API response (just percentages and reset timestamps) gets cached in
memory between polls. The token is re-read fresh from the credentials file
every time, so token refreshes by Claude Code itself are picked up
automatically.

## A heads-up on the endpoint

`/api/oauth/usage` is the internal endpoint that Claude Code's `/usage`
command calls. It's not part of Anthropic's documented public API. If they
ever change or remove it, this widget will start showing the OFFLINE state
and fall back to counting tokens from the local JSONL files. That fallback
will basically never break since it just reads files on disk.

## License

MIT. Do whatever you want with it.
