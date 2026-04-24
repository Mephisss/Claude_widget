"""First-run wizard: locate the Claude Code credentials file.

Auto-skips when load_token() works with the configured (or default) path.
The wizard never displays or stores the token itself.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import auth


def _candidate_paths() -> list[Path]:
    home = Path(os.path.expanduser("~"))
    paths: list[Path] = [home / ".claude" / ".credentials.json"]

    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        local = os.environ.get("LOCALAPPDATA")
        if appdata:
            paths.append(Path(appdata) / "Claude" / ".credentials.json")
            paths.append(Path(appdata) / "Claude Code" / ".credentials.json")
            paths.append(Path(appdata) / "claude-cli-nodejs" / ".credentials.json")
        if local:
            paths.append(Path(local) / "Claude" / ".credentials.json")
            paths.append(Path(local) / "Claude Code" / ".credentials.json")
            paths.append(Path(local) / "claude-cli-nodejs" / ".credentials.json")
    elif sys.platform == "darwin":
        appsup = home / "Library" / "Application Support"
        paths += [
            appsup / "Claude" / ".credentials.json",
            appsup / "Claude Code" / ".credentials.json",
            appsup / "anthropic" / ".credentials.json",
        ]
    else:
        xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
        paths += [
            xdg / "claude" / ".credentials.json",
            xdg / "Claude" / ".credentials.json",
            xdg / "anthropic" / ".credentials.json",
        ]

    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def discover_suggestions() -> list[tuple[Path, bool]]:
    found: list[tuple[Path, bool]] = []
    saved = auth.CREDENTIALS_PATH
    try:
        for p in _candidate_paths():
            if not p.is_file():
                continue
            auth.set_credentials_path(str(p))
            try:
                auth.load_token()
                valid = True
            except auth.TokenError:
                valid = False
            found.append((p, valid))
    finally:
        auth.CREDENTIALS_PATH = saved
    return found


def _credentials_work(custom_path: str | None) -> bool:
    auth.set_credentials_path(custom_path)
    try:
        auth.load_token()
        return True
    except auth.TokenError:
        return False


def needs_wizard(cfg: dict) -> bool:
    if cfg.get("first_run_complete") and _credentials_work(cfg.get("credentials_path")):
        return False
    return not _credentials_work(cfg.get("credentials_path"))


class _Wizard:
    def __init__(self, cfg: dict) -> None:
        self.cfg = dict(cfg)
        self.cancelled = True

        self.win = tk.Tk()
        self.win.title("Claude Widget · Setup")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self._build()
        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")

    def _build(self) -> None:
        outer = ttk.Frame(self.win, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Welcome to Claude Widget",
                  font=("", 12, "bold")).pack(anchor="w")
        ttk.Label(outer,
                  text="We couldn't auto-detect your Claude Code credentials.\n"
                       "Pick one of the suggestions below, or point us at the file.",
                  justify="left").pack(anchor="w", pady=(4, 12))

        self.path_var = tk.StringVar(
            value=self.cfg.get("credentials_path") or str(auth.DEFAULT_CREDENTIALS_PATH)
        )

        ttk.Label(outer, text="Suggestions found on this system:",
                  foreground="#666").pack(anchor="w")
        sugg_frame = ttk.Frame(outer)
        sugg_frame.pack(fill="x", pady=(4, 10))

        suggestions = discover_suggestions()
        if not suggestions:
            ttk.Label(sugg_frame,
                      text="(no .credentials.json found in any common location — "
                           "browse manually below)",
                      foreground="#888").pack(anchor="w")
            self._show_common_locations(sugg_frame)
        else:
            for path, valid in suggestions:
                self._add_suggestion_row(sugg_frame, path, valid)

        ttk.Label(outer, text="Custom path:").pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(outer)
        row.pack(fill="x", pady=(4, 4))
        ttk.Entry(row, textvariable=self.path_var, width=58).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(row, text="Browse…", command=self._browse).pack(side="left", padx=(6, 0))

        if sys.platform == "darwin":
            ttk.Label(outer, text="(macOS Keychain is also tried automatically.)",
                      foreground="#666").pack(anchor="w", pady=(4, 0))

        self.test_label = ttk.Label(outer, text="", foreground="#666")
        self.test_label.pack(anchor="w", pady=(8, 0))

        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Test", command=self._test).pack(side="left")
        ttk.Button(btns, text="Skip", command=self._skip).pack(side="right")
        ttk.Button(btns, text="Save & Continue", command=self._save).pack(side="right", padx=6)

        self.win.protocol("WM_DELETE_WINDOW", self._skip)

    def _add_suggestion_row(self, parent: ttk.Frame, path: Path, valid: bool) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=1)
        badge = "✓ Valid" if valid else "Found"
        col = "#0a0" if valid else "#888"
        ttk.Label(row, text=badge, foreground=col, width=8, anchor="w").pack(side="left")
        path_lbl = ttk.Label(row, text=str(path), font=("Consolas", 9), foreground="#222")
        path_lbl.pack(side="left", fill="x", expand=True)

        def _use(_evt=None, p=path):
            self.path_var.set(str(p))
            self._test()
        ttk.Button(row, text="Use", width=6, command=_use).pack(side="right")
        path_lbl.bind("<Button-1>", _use)

    def _show_common_locations(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Try these paths:", foreground="#666").pack(
            anchor="w", pady=(8, 2)
        )
        for p in _candidate_paths():
            ttk.Label(parent, text=f"  • {p}", font=("Consolas", 9),
                      foreground="#444").pack(anchor="w")

    def _browse(self) -> None:
        initial = os.path.expanduser("~/.claude")
        chosen = filedialog.askopenfilename(
            parent=self.win,
            title="Locate .credentials.json",
            initialdir=initial if os.path.isdir(initial) else os.path.expanduser("~"),
            filetypes=[("JSON credential file", "*.json"), ("All files", "*.*")],
        )
        if chosen:
            self.path_var.set(chosen)

    def _test(self) -> bool:
        p = self.path_var.get().strip() or None
        ok = _credentials_work(p)
        if ok:
            self.test_label.configure(text="✓ Credentials valid", foreground="#0a0")
        else:
            self.test_label.configure(text="✗ Could not read credentials at that path",
                                      foreground="#c33")
        return ok

    def _save(self) -> None:
        if not self._test():
            return
        p = self.path_var.get().strip()
        self.cfg["credentials_path"] = p or None
        self.cfg["first_run_complete"] = True
        self.cancelled = False
        self.win.destroy()

    def _skip(self) -> None:
        self.cfg["first_run_complete"] = True
        self.cancelled = False
        self.win.destroy()

    def run(self) -> dict:
        self.win.mainloop()
        return self.cfg


def maybe_run(cfg: dict) -> dict:
    if not needs_wizard(cfg):
        cfg["first_run_complete"] = True
        auth.set_credentials_path(cfg.get("credentials_path"))
        return cfg
    new_cfg = _Wizard(cfg).run()
    auth.set_credentials_path(new_cfg.get("credentials_path"))
    return new_cfg
