"""Always-on-top widget showing live Claude session + weekly utilization."""
from __future__ import annotations

import json
import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from live_usage import LiveUsage, LiveUsageError, RateLimited, fetch as fetch_live
from usage import collect as collect_local, fmt_tokens, short_model
from windows_glass import apply_acrylic, apply_mica, apply_rounded


def _default_mono_font() -> str:
    if sys.platform.startswith("win"):
        return "Cascadia Mono"
    if sys.platform == "darwin":
        return "Menlo"
    return "DejaVu Sans Mono"


HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"

THEMES = {
    "claude_code": {
        "fg": "#e6e6e6",
        "fg_dim": "#a8a8a8",
        "fg_muted": "#6a6a6a",
        "track": "#2a2a2a",
        "card": "#1a1a1a",
        "border": "#cc785c",
        "accent": "#cc785c",
        "good": "#cc785c",
        "warn": "#e9a76d",
        "crit": "#e07b5b",
    },
    "dark": {
        "fg": "#f1f3f8",
        "fg_dim": "#9aa0b4",
        "fg_muted": "#5f6478",
        "track": "#272a36",
        "card": "#161821",
        "border": "#3a3f55",
        "accent": "#7c9cff",
        "good": "#5eead4",
        "warn": "#fbbf24",
        "crit": "#f87171",
    },
    "light": {
        "fg": "#10131a",
        "fg_dim": "#3f4456",
        "fg_muted": "#7a8095",
        "track": "#d8dbe6",
        "card": "#f4f5f9",
        "border": "#c2c5d1",
        "accent": "#3b67ff",
        "good": "#0d9488",
        "warn": "#d97706",
        "crit": "#dc2626",
    },
}

DEFAULTS = {
    "refresh_seconds": 60,
    "alpha": 0.95,
    "x": None,
    "y": None,
    "width": 320,
    "height": 170,
    "theme": "claude_code",
    "backdrop": "solid",
    "tint": "#0d0d12",
    "tint_alpha": 170,
    "accent": "#cc785c",
    "rounded": True,
    "show_per_model": True,
    "show_reset_time": True,
    "font_family": _default_mono_font(),
    "font_scale": 1.0,
    "title": "Claude Usage",
    "always_on_top": True,
    "tray_enabled": True,
    "glitch_on_open": True,
    "glitch_on_close": True,
    "credentials_path": None,
    "first_run_complete": False,
}

GRIP_SIZE = 14
MIN_WIDTH = 160
MIN_HEIGHT = 56
COMPACT_W_THRESHOLD = 280
COMPACT_H_THRESHOLD = 110
EXPANDED_H_THRESHOLD = 260


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _mix(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(_lerp(r1, r2, t), _lerp(g1, g2, t), _lerp(b1, b2, t))


def bar_color_for(pct: float, palette: dict) -> str:
    p = max(0.0, min(pct / 100.0, 1.0))
    if p < 0.5:
        return _mix(palette["good"], palette["warn"], p / 0.5)
    return _mix(palette["warn"], palette["crit"], (p - 0.5) / 0.5)


@dataclass(slots=True)
class _DragState:
    dx: int = 0
    dy: int = 0
    dragging: bool = False


@dataclass(slots=True)
class _ResizeState:
    start_w: int = 0
    start_h: int = 0
    start_root_x: int = 0
    start_root_y: int = 0
    resizing: bool = False


class Widget:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.last_live: LiveUsage | None = None
        self.using_fallback = False
        self.next_refresh_in: int | None = None
        self._font_cache: dict[tuple, tkfont.Font] = {}
        self._tray = None
        self._closing = False
        # Hold a ref to the PhotoImage so Tk doesn't garbage-collect the icon.
        self._icon_image = None

        self.root = tk.Tk()
        self.root.title("claude-widget")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
        self.root.attributes("-alpha", float(self.cfg.get("alpha", 0.95)))
        self._topmost_var = tk.BooleanVar(value=bool(self.cfg.get("always_on_top", True)))

        card_bg = THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])["card"]
        self.root.configure(bg=card_bg)

        self._place_window()

        self.canvas = tk.Canvas(
            self.root,
            width=self.cfg["width"],
            height=self.cfg["height"],
            bg=card_bg,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self._drag = _DragState()
        self._resize = _ResizeState()
        # Bind to both canvas and root so events fire regardless of which child catches them.
        for widget in (self.canvas, self.root):
            for ev, h in (
                ("<ButtonPress-1>", self._on_press),
                ("<B1-Motion>", self._on_drag),
                ("<ButtonRelease-1>", self._on_release),
                ("<Button-3>", self._on_menu),
                ("<Double-Button-1>", lambda e: self.refresh()),
                ("<Motion>", self._on_motion),
            ):
                widget.bind(ev, h)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Refresh now", command=self.refresh)
        self.menu.add_checkbutton(label="Always on top",
                                  variable=self._topmost_var,
                                  command=self._toggle_topmost)
        self.menu.add_command(label="Send to back", command=self._send_to_back)
        self.menu.add_separator()
        self.menu.add_command(label="Settings…", command=self._open_settings)
        self.menu.add_command(label="Re-run setup…", command=self._rerun_setup)
        self.menu.add_separator()
        self.menu.add_command(label="Close", command=self._quit)

        self.root.after(50, self._apply_backdrop)
        self.root.after(80, self._first_frame)
        self._install_window_icon()
        if self.cfg.get("tray_enabled", True):
            self.root.after(120, self._start_tray)

    def _place_window(self) -> None:
        w, h = int(self.cfg["width"]), int(self.cfg["height"])
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            x, y = sw - w - 24, 24
        x = max(0, min(int(x), sw - w))
        y = max(0, min(int(y), sh - h))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_backdrop(self) -> None:
        backdrop = self.cfg.get("backdrop", "solid")
        if self.cfg.get("rounded", True):
            apply_rounded(self.root)
        # `acrylic_experimental` requires -transparentcolor which breaks click handling
        # and ClearType — left as opt-in for users who want the effect anyway.
        if backdrop == "mica":
            apply_mica(self.root)
        elif backdrop == "acrylic_experimental":
            apply_acrylic(self.root, self.cfg.get("tint", "#0d0d12"),
                          int(self.cfg.get("tint_alpha", 170)))

    def _local_xy(self, e) -> tuple[int, int]:
        return e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _in_grip(self, x: int, y: int) -> bool:
        w, h = int(self.cfg["width"]), int(self.cfg["height"])
        return x >= w - GRIP_SIZE - 2 and y >= h - GRIP_SIZE - 2

    def _on_motion(self, e):
        if self._drag.dragging or self._resize.resizing:
            return
        x, y = self._local_xy(e)
        cursor = "size_nw_se" if self._in_grip(x, y) else ""
        try:
            self.root.config(cursor=cursor)
        except tk.TclError:
            pass

    def _on_press(self, e):
        x, y = self._local_xy(e)
        if self._in_grip(x, y):
            self._resize = _ResizeState(
                start_w=int(self.cfg["width"]),
                start_h=int(self.cfg["height"]),
                start_root_x=e.x_root,
                start_root_y=e.y_root,
                resizing=True,
            )
            return
        self._drag = _DragState(
            dx=e.x_root - self.root.winfo_x(),
            dy=e.y_root - self.root.winfo_y(),
            dragging=True,
        )

    def _on_drag(self, e):
        if self._resize.resizing:
            new_w = max(MIN_WIDTH, self._resize.start_w + (e.x_root - self._resize.start_root_x))
            new_h = max(MIN_HEIGHT, self._resize.start_h + (e.y_root - self._resize.start_root_y))
            self.cfg["width"] = new_w
            self.cfg["height"] = new_h
            self.root.geometry(
                f"{new_w}x{new_h}+{self.root.winfo_x()}+{self.root.winfo_y()}"
            )
            self.canvas.configure(width=new_w, height=new_h)
            self._redraw_current()
            return
        if not self._drag.dragging:
            return
        self.root.geometry(f"+{e.x_root - self._drag.dx}+{e.y_root - self._drag.dy}")

    def _on_release(self, _e):
        if self._resize.resizing:
            self._resize.resizing = False
            save_config(self.cfg)
            self._redraw_current()
            return
        if not self._drag.dragging:
            return
        self._drag.dragging = False
        self.cfg["x"] = self.root.winfo_x()
        self.cfg["y"] = self.root.winfo_y()
        save_config(self.cfg)

    def _redraw_current(self) -> None:
        if self.last_live is not None and not self.using_fallback:
            self._draw_live(self.last_live)
        else:
            self._draw_fallback("resizing")

    def _on_menu(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _quit(self):
        if self._closing:
            return
        self._closing = True

        def _finish():
            try:
                if self._tray is not None:
                    self._tray.stop()
            finally:
                try:
                    self.root.destroy()
                except tk.TclError:
                    pass

        if self.cfg.get("glitch_on_close", True):
            try:
                import glitch
                accent = self._palette().get("accent", "#cc785c")
                glitch.animate(
                    self.canvas, self.root,
                    mode="out", duration_ms=380, frames=12, accent=accent,
                    on_each_frame=lambda i: self._fade_alpha(i),
                    on_done=_finish,
                )
                return
            except Exception:
                pass
        _finish()

    def _fade_alpha(self, intensity: float) -> None:
        a = max(0.0, float(self.cfg.get("alpha", 0.95)) * (1.0 - intensity * 1.05))
        try:
            self.root.attributes("-alpha", a)
        except tk.TclError:
            pass

    def _first_frame(self) -> None:
        self.refresh()
        if self.cfg.get("glitch_on_open", True):
            accent = self._palette().get("accent", "#cc785c")
            try:
                import glitch
                glitch.animate(
                    self.canvas, self.root,
                    mode="in", duration_ms=380, frames=12, accent=accent,
                )
            except Exception:
                pass
        # Free the PIL.Image referenced by mascot.build()'s LRU after the icon
        # and tray are established — the running widget no longer needs it.
        self.root.after(2000, self._post_init_gc)

    def _post_init_gc(self) -> None:
        try:
            import mascot
            mascot.build.cache_clear()
        except Exception:
            pass
        import gc
        gc.collect()

    def _install_window_icon(self) -> None:
        try:
            import mascot
            from PIL import ImageTk
            img = mascot.build(64)
            self._icon_image = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self._icon_image)
        except Exception:
            pass

    def _start_tray(self) -> None:
        try:
            from tray import Tray
        except Exception:
            return
        self._tray = Tray(
            title=self.cfg.get("title", "Claude Usage"),
            on_show=lambda: self.root.after(0, self.show),
            on_hide=lambda: self.root.after(0, self.hide),
            on_toggle=lambda: self.root.after(0, self.toggle_visibility),
            on_refresh=lambda: self.root.after(0, self.refresh),
            on_quit=lambda: self.root.after(0, self._quit),
        )
        self._tray.start()

    def show(self) -> None:
        try:
            self.root.deiconify()
            if self.cfg.get("always_on_top", True):
                self.root.attributes("-topmost", True)
            self.root.lift()
        except tk.TclError:
            pass

    def hide(self) -> None:
        try:
            self.root.withdraw()
        except tk.TclError:
            pass

    def toggle_visibility(self) -> None:
        try:
            visible = self.root.state() != "withdrawn"
        except tk.TclError:
            visible = True
        if visible:
            self.hide()
        else:
            self.show()

    def _toggle_topmost(self) -> None:
        on = bool(self._topmost_var.get())
        self.root.attributes("-topmost", on)
        self.cfg["always_on_top"] = on
        save_config(self.cfg)

    def _send_to_back(self) -> None:
        # Lower only sticks if -topmost is off, so disable it (and persist) before lowering.
        self._topmost_var.set(False)
        self.root.attributes("-topmost", False)
        self.cfg["always_on_top"] = False
        save_config(self.cfg)
        self.root.lower()

    def _palette(self) -> dict:
        return THEMES.get(self.cfg.get("theme", "dark"), THEMES["dark"])

    def _font(self, size: int, weight: str = "normal") -> tkfont.Font:
        scale = float(self.cfg.get("font_scale", 1.0))
        family = self.cfg.get("font_family", _default_mono_font())
        px = max(7, int(round(size * scale)))
        key = (family, px, weight)
        f = self._font_cache.get(key)
        if f is None:
            f = tkfont.Font(family=family, size=px, weight=weight)
            self._font_cache[key] = f
        return f

    def _draw_bar(self, x: int, y: int, w: int, pct: float, palette: dict, height: int = 6) -> None:
        c = self.canvas
        c.create_rectangle(x, y, x + w, y + height, fill=palette["track"], outline="")
        frac = max(0.0, min(pct / 100.0, 1.0))
        if frac <= 0:
            return
        fill_w = max(2, int(w * frac))
        if self.cfg.get("theme") == "claude_code":
            c.create_rectangle(x, y, x + fill_w, y + height, fill=palette["accent"], outline="")
            return
        steps = max(4, fill_w // 4)
        start = palette["good"]
        end = bar_color_for(pct, palette)
        for i in range(steps):
            color = _mix(start, end, (i + 0.5) / steps)
            x1 = x + int(fill_w * (i / steps))
            x2 = x + int(fill_w * ((i + 1) / steps)) + 1
            c.create_rectangle(x1, y, x2, y + height, fill=color, outline="")

    def _draw_row(self, x: int, y: int, w: int, label: str, pct: float, sub_left: str, sub_right: str) -> None:
        c = self.canvas
        pal = self._palette()
        bar_y = y + 30
        baseline = bar_y - 6
        is_cc = self.cfg.get("theme") == "claude_code"
        label_color = pal.get("accent", pal["fg_dim"]) if is_cc else pal["fg_dim"]

        c.create_text(x, baseline, anchor="sw", text=label,
                      fill=label_color, font=self._font(10 if is_cc else 9, "bold"))
        c.create_text(x + w, baseline, anchor="se", text=f"{pct:.0f}%",
                      fill=pal["fg"], font=self._font(20, "bold"))
        self._draw_bar(x, bar_y, w, pct, pal)
        c.create_text(x, bar_y + 14, anchor="w", text=sub_left, fill=pal["fg_dim"],
                      font=self._font(8))
        if sub_right:
            c.create_text(x + w, bar_y + 14, anchor="e", text=sub_right, fill=pal["fg_muted"],
                          font=self._font(8))

    def _draw_resize_grip(self) -> None:
        c = self.canvas
        pal = self._palette()
        w, h = int(self.cfg["width"]), int(self.cfg["height"])
        for off in (3, 6, 9):
            c.create_line(w - off - 2, h - 2, w - 2, h - off - 2, fill=pal["fg_muted"])

    def _draw_titled_border(self, title: str, status_text: str = "", status_color: str | None = None) -> tuple[int, int]:
        c = self.canvas
        pal = self._palette()
        w, h = int(self.cfg["width"]), int(self.cfg["height"])
        is_cc = self.cfg.get("theme") == "claude_code"
        m = 8
        bx0, by0, bx1, by1 = m, m, w - m, h - m
        border_col = pal.get("border", pal["fg_muted"])
        c.create_rectangle(bx0, by0, bx1, by1, outline=border_col, width=1)

        title_text = f" {title} "
        version = "  v1" if is_cc else ""
        title_font = self._font(9, "bold")
        try:
            f = tkfont.Font(font=title_font)
            tw = f.measure(title_text + version)
        except Exception:
            f = None
            tw = 8 * len(title_text + version)

        title_x = bx0 + 18
        c.create_rectangle(title_x - 4, by0 - 1, title_x + tw + 6, by0 + 1,
                           fill=pal["card"], outline="")
        c.create_text(title_x, by0, anchor="w", text=title_text.strip(),
                      fill=border_col, font=title_font)
        if version and f is not None:
            c.create_text(title_x + f.measure(title_text), by0, anchor="w",
                          text=version, fill=pal["fg_muted"], font=self._font(8))

        if status_text:
            sf = self._font(8)
            try:
                sw = tkfont.Font(font=sf).measure(status_text)
            except Exception:
                sw = 7 * len(status_text)
            sx = bx1 - 18 - sw
            c.create_rectangle(sx - 4, by0 - 1, bx1 - 14, by0 + 1,
                               fill=pal["card"], outline="")
            c.create_text(sx, by0, anchor="w", text=status_text,
                          fill=status_color or pal["fg_muted"], font=sf)

        return bx0 + 14, by0 + 14

    def _layout_mode(self) -> str:
        h = int(self.cfg["height"])
        w = int(self.cfg["width"])
        if h < COMPACT_H_THRESHOLD or w < COMPACT_W_THRESHOLD:
            return "compact"
        if h >= EXPANDED_H_THRESHOLD:
            return "expanded"
        return "normal"

    def _draw_live(self, u: LiveUsage, stale_reason: str = "") -> None:
        mode = self._layout_mode()
        if mode == "compact":
            self._draw_live_compact(u, stale_reason)
        elif mode == "expanded":
            self._draw_live_expanded(u, stale_reason)
        else:
            self._draw_live_normal(u, stale_reason)

    def _status_line(self, stale_reason: str) -> tuple[str, str]:
        pal = self._palette()
        if stale_reason:
            return f"● STALE · {stale_reason}", pal["warn"]
        return f"● LIVE · {datetime.now().strftime('%H:%M')}", pal.get("accent", pal["good"])

    def _draw_live_compact(self, u: LiveUsage, stale_reason: str = "") -> None:
        """Two big % numbers with small captions to their right, centered horizontally."""
        c = self.canvas
        c.delete("all")
        pal = self._palette()
        w, h = int(self.cfg["width"]), int(self.cfg["height"])
        accent = pal.get("accent", pal["good"])
        sess_col = pal["warn"] if stale_reason else accent

        big_size = max(14, min(28, h - 22))
        cap_size = max(7, min(11, big_size // 3 + 2))

        big_font = self._font(big_size, "bold")
        cap_font = self._font(cap_size, "bold")

        sess_num = f"{u.session.utilization_pct:.0f}%"
        week_num = f"{u.week.utilization_pct:.0f}%"

        gap_num_cap = 4
        gap_pairs = max(10, w // 24)

        sess_w = big_font.measure(sess_num) + gap_num_cap + cap_font.measure("current")
        week_w = big_font.measure(week_num) + gap_num_cap + cap_font.measure("weekly")
        total_w = sess_w + gap_pairs + week_w

        start_x = max(8, (w - total_w) // 2)
        cy = h // 2

        x = start_x
        c.create_text(x, cy, anchor="w", text=sess_num, fill=pal["fg"], font=big_font)
        x += big_font.measure(sess_num) + gap_num_cap
        c.create_text(x, cy + 2, anchor="w", text="current", fill=sess_col, font=cap_font)
        x += cap_font.measure("current") + gap_pairs

        c.create_text(x, cy, anchor="w", text=week_num, fill=pal["fg"], font=big_font)
        x += big_font.measure(week_num) + gap_num_cap
        c.create_text(x, cy + 2, anchor="w", text="weekly", fill=accent, font=cap_font)

        if stale_reason and h >= 70:
            c.create_text(w // 2, h - 10, anchor="s", text=stale_reason,
                          fill=pal["warn"], font=self._font(7))

        self._draw_resize_grip()

    def _draw_live_normal(self, u: LiveUsage, stale_reason: str = "") -> None:
        c = self.canvas
        c.delete("all")
        pal = self._palette()
        w, _h = int(self.cfg["width"]), int(self.cfg["height"])
        status, status_col = self._status_line(stale_reason)
        title = self.cfg.get("title", "Claude Usage")
        ix, iy = self._draw_titled_border(title, status, status_col)
        inner = w - 2 * ix

        ROW_STRIDE = 64
        row1_y = iy + 4
        row2_y = row1_y + ROW_STRIDE

        sub_r_session = f"resets in {u.session.time_left()}" if self.cfg.get("show_reset_time", True) else ""
        self._draw_row(
            ix, row1_y, inner,
            label="SESSION · 5h",
            pct=u.session.utilization_pct,
            sub_left=f"{100 - u.session.utilization_pct:.0f}% remaining",
            sub_right=sub_r_session,
        )

        bits: list[str] = []
        if self.cfg.get("show_per_model", True):
            if u.week_opus:
                bits.append(f"opus {u.week_opus.utilization_pct:.0f}%")
            if u.week_sonnet:
                bits.append(f"sonnet {u.week_sonnet.utilization_pct:.0f}%")
        sub_r_week = f"resets in {u.week.time_left()}" if self.cfg.get("show_reset_time", True) else ""
        self._draw_row(
            ix, row2_y, inner,
            label="WEEK · 7d",
            pct=u.week.utilization_pct,
            sub_left=" · ".join(bits) if bits else f"{100 - u.week.utilization_pct:.0f}% remaining",
            sub_right=sub_r_week,
        )
        self._draw_resize_grip()

    def _draw_live_expanded(self, u: LiveUsage, stale_reason: str = "") -> None:
        c = self.canvas
        c.delete("all")
        pal = self._palette()
        w, h = int(self.cfg["width"]), int(self.cfg["height"])
        status, status_col = self._status_line(stale_reason)
        title = self.cfg.get("title", "Claude Usage")
        ix, iy = self._draw_titled_border(title, status, status_col)
        inner = w - 2 * ix

        ROW_STRIDE = 64
        row1_y = iy + 4
        row2_y = row1_y + ROW_STRIDE
        sub_r_session = f"resets in {u.session.time_left()}" if self.cfg.get("show_reset_time", True) else ""
        sub_r_week = f"resets in {u.week.time_left()}" if self.cfg.get("show_reset_time", True) else ""

        self._draw_row(ix, row1_y, inner, "SESSION · 5h",
                       u.session.utilization_pct,
                       f"{100 - u.session.utilization_pct:.0f}% remaining",
                       sub_r_session)
        self._draw_row(ix, row2_y, inner, "WEEK · 7d",
                       u.week.utilization_pct,
                       f"{100 - u.week.utilization_pct:.0f}% remaining",
                       sub_r_week)

        sec_y = row2_y + ROW_STRIDE - 8
        c.create_line(ix, sec_y, ix + inner, sec_y, fill=pal["track"])
        c.create_text(ix, sec_y + 6, anchor="nw",
                      text="PER BUCKET · 7d",
                      fill=pal.get("accent", pal["fg_dim"]),
                      font=self._font(9, "bold"))
        sec_y += 24

        rows = u.per_model_breakdown()
        if not rows:
            c.create_text(ix, sec_y, anchor="nw",
                          text="(no per-bucket data reported)",
                          fill=pal["fg_muted"], font=self._font(8))
        else:
            for label, win in rows:
                if sec_y + 14 > h - 20:
                    break
                c.create_text(ix, sec_y, anchor="w", text=label,
                              fill=pal["fg_dim"], font=self._font(9))
                bar_x = ix + 110
                bar_w = inner - 110 - 50
                if bar_w > 30:
                    self._draw_bar(bar_x, sec_y - 3, bar_w, win.utilization_pct, pal, height=5)
                c.create_text(ix + inner, sec_y, anchor="e",
                              text=f"{win.utilization_pct:.0f}%",
                              fill=pal["fg"], font=self._font(9, "bold"))
                sec_y += 18

        if h - sec_y > 30:
            try:
                session_local, week_local = collect_local()
                c.create_text(ix, h - 22, anchor="w",
                              text=f"local: {fmt_tokens(session_local.billable_tokens)} session · "
                                   f"{fmt_tokens(week_local.billable_tokens)} week",
                              fill=pal["fg_muted"], font=self._font(8))
            except Exception:
                pass

        self._draw_resize_grip()

    def _draw_fallback(self, msg: str) -> None:
        c = self.canvas
        pal = self._palette()
        try:
            session, week = collect_local()
        except Exception as exc:
            self._draw_error(f"local fallback failed: {exc}")
            return
        c.delete("all")

        if self._layout_mode() == "compact":
            w, h = int(self.cfg["width"]), int(self.cfg["height"])
            big = self._font(max(14, min(22, h - 24)), "bold")
            cap = self._font(8, "bold")
            s_txt = fmt_tokens(session.billable_tokens)
            w_txt = fmt_tokens(week.billable_tokens)
            gap = 12
            total = big.measure(s_txt) + 4 + cap.measure("session") + gap \
                    + big.measure(w_txt) + 4 + cap.measure("week")
            x = max(6, (w - total) // 2)
            cy = h // 2
            c.create_text(x, cy, anchor="w", text=s_txt, fill=pal["fg"], font=big)
            x += big.measure(s_txt) + 4
            c.create_text(x, cy + 1, anchor="w", text="session", fill=pal["warn"], font=cap)
            x += cap.measure("session") + gap
            c.create_text(x, cy, anchor="w", text=w_txt, fill=pal["fg"], font=big)
            x += big.measure(w_txt) + 4
            c.create_text(x, cy + 1, anchor="w", text="week", fill=pal["warn"], font=cap)
            self._draw_resize_grip()
            return

        title = self.cfg.get("title", "Claude Usage")
        ix, iy = self._draw_titled_border(title, f"● OFFLINE · {msg[:24]}", pal["warn"])

        c.create_text(ix, iy + 4, anchor="nw", text="SESSION · 5h",
                      fill=pal.get("accent", pal["fg_dim"]), font=self._font(10, "bold"))
        c.create_text(ix, iy + 22, anchor="nw", text=fmt_tokens(session.billable_tokens),
                      fill=pal["fg"], font=self._font(16, "bold"))
        models_s = sorted(session.by_model.items(), key=lambda x: -x[1])[:2]
        c.create_text(ix, iy + 46, anchor="nw",
                      text=" · ".join(f"{short_model(m)} {fmt_tokens(t)}" for m, t in models_s if t),
                      fill=pal["fg_muted"], font=self._font(8))

        c.create_text(ix, iy + 68, anchor="nw", text="WEEK · 7d",
                      fill=pal.get("accent", pal["fg_dim"]), font=self._font(10, "bold"))
        c.create_text(ix, iy + 86, anchor="nw", text=fmt_tokens(week.billable_tokens),
                      fill=pal["fg"], font=self._font(16, "bold"))
        models_w = sorted(week.by_model.items(), key=lambda x: -x[1])[:2]
        c.create_text(ix, iy + 110, anchor="nw",
                      text=" · ".join(f"{short_model(m)} {fmt_tokens(t)}" for m, t in models_w if t),
                      fill=pal["fg_muted"], font=self._font(8))
        self._draw_resize_grip()

    def _draw_error(self, msg: str) -> None:
        pal = self._palette()
        c = self.canvas
        c.delete("all")
        c.create_text(14, 14, anchor="nw", text="ERROR", fill=pal["crit"], font=self._font(9, "bold"))
        c.create_text(14, 32, anchor="nw", text=msg[:240], fill=pal["fg"],
                      font=self._font(8), width=int(self.cfg["width"]) - 28)

    def refresh(self):
        try:
            u = fetch_live()
        except RateLimited as exc:
            self.next_refresh_in = max(60, exc.retry_after)
            if self.last_live is not None:
                self._draw_live(self.last_live, stale_reason=f"rate-limited · retry {exc.retry_after}s")
            else:
                self.using_fallback = True
                self._draw_fallback(str(exc))
        except LiveUsageError as exc:
            self.using_fallback = True
            self._draw_fallback(str(exc))
        except Exception as exc:
            self._draw_error(f"unexpected: {exc}")
        else:
            self.last_live = u
            self.using_fallback = False
            self._draw_live(u)
        self._reschedule()

    def _reschedule(self):
        if self.next_refresh_in is not None:
            secs = self.next_refresh_in
            self.next_refresh_in = None
        else:
            secs = int(self.cfg.get("refresh_seconds", 60))
        self.root.after(max(5, secs) * 1000, self.refresh)

    def _open_settings(self):
        SettingsDialog(self)

    def _rerun_setup(self) -> None:
        import auth
        from first_run import _Wizard
        self.cfg["first_run_complete"] = False
        new_cfg = _Wizard(self.cfg).run()
        self.cfg.update(new_cfg)
        save_config(self.cfg)
        auth.set_credentials_path(self.cfg.get("credentials_path"))
        self.refresh()

    def apply_settings(self, new_cfg: dict) -> None:
        old_size = (self.cfg["width"], self.cfg["height"])
        old_font = (self.cfg.get("font_family"), self.cfg.get("font_scale"))
        self.cfg.update(new_cfg)
        save_config(self.cfg)

        if (self.cfg.get("font_family"), self.cfg.get("font_scale")) != old_font:
            self._font_cache.clear()

        self.root.attributes("-alpha", float(self.cfg["alpha"]))
        card_bg = self._palette()["card"]
        self.root.configure(bg=card_bg)
        self.canvas.configure(bg=card_bg)
        if (self.cfg["width"], self.cfg["height"]) != old_size:
            self.root.geometry(f'{int(self.cfg["width"])}x{int(self.cfg["height"])}'
                               f'+{self.root.winfo_x()}+{self.root.winfo_y()}')
            self.canvas.config(width=int(self.cfg["width"]), height=int(self.cfg["height"]))
        self._apply_backdrop()
        self.refresh()

    def run(self):
        self.root.mainloop()


class SettingsDialog:
    def __init__(self, owner: Widget):
        self.owner = owner
        self.win = tk.Toplevel(owner.root)
        self.win.title("Widget settings")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.transient(owner.root)

        self._vars: dict[str, tk.Variable] = {}
        self._build()

    def _add_row(self, parent, label, var, width=14):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=18, anchor="w").pack(side="left")
        ttk.Entry(row, textvariable=var, width=width).pack(side="left")

    def _add_combo(self, parent, label, var, values):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=18, anchor="w").pack(side="left")
        ttk.Combobox(row, textvariable=var, values=values, state="readonly", width=12).pack(side="left")

    def _add_check(self, parent, label, var):
        ttk.Checkbutton(parent, text=label, variable=var).pack(anchor="w", pady=2)

    def _build(self):
        cfg = self.owner.cfg
        outer = ttk.Frame(self.win, padding=12)
        outer.pack(fill="both", expand=True)

        v = self._vars
        v["width"] = tk.IntVar(value=cfg["width"])
        v["height"] = tk.IntVar(value=cfg["height"])
        v["alpha"] = tk.DoubleVar(value=cfg["alpha"])
        v["refresh_seconds"] = tk.IntVar(value=cfg["refresh_seconds"])
        v["theme"] = tk.StringVar(value=cfg["theme"])
        v["backdrop"] = tk.StringVar(value=cfg["backdrop"])
        v["tint"] = tk.StringVar(value=cfg["tint"])
        v["tint_alpha"] = tk.IntVar(value=cfg["tint_alpha"])
        v["accent"] = tk.StringVar(value=cfg["accent"])
        v["font_family"] = tk.StringVar(value=cfg["font_family"])
        v["font_scale"] = tk.DoubleVar(value=cfg["font_scale"])
        v["rounded"] = tk.BooleanVar(value=cfg["rounded"])
        v["show_per_model"] = tk.BooleanVar(value=cfg["show_per_model"])
        v["show_reset_time"] = tk.BooleanVar(value=cfg["show_reset_time"])
        v["title"] = tk.StringVar(value=cfg.get("title", "Claude Usage"))

        ttk.Label(outer, text="Layout", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        self._add_row(outer, "Width (px)", v["width"], 8)
        self._add_row(outer, "Height (px)", v["height"], 8)
        self._add_row(outer, "Opacity (0.2–1.0)", v["alpha"], 8)
        self._add_row(outer, "Refresh (sec)", v["refresh_seconds"], 8)

        ttk.Separator(outer).pack(fill="x", pady=8)
        ttk.Label(outer, text="Appearance", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        self._add_combo(outer, "Theme", v["theme"], ["claude_code", "dark", "light"])
        self._add_combo(outer, "Backdrop", v["backdrop"], ["solid", "mica", "acrylic_experimental"])
        self._add_row(outer, "Tint (#rrggbb)", v["tint"])
        self._add_row(outer, "Tint alpha (0–255)", v["tint_alpha"], 8)
        self._add_row(outer, "Accent (#rrggbb)", v["accent"])
        self._add_row(outer, "Font family", v["font_family"], 18)
        self._add_row(outer, "Font scale", v["font_scale"], 8)
        self._add_check(outer, "Rounded corners", v["rounded"])

        ttk.Separator(outer).pack(fill="x", pady=8)
        ttk.Label(outer, text="Content", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        self._add_check(outer, "Show per-model breakdown", v["show_per_model"])
        self._add_check(outer, "Show reset times", v["show_reset_time"])
        self._add_row(outer, "Title", v["title"], 18)

        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Reset", command=self._reset).pack(side="left")
        ttk.Button(btns, text="Cancel", command=self.win.destroy).pack(side="right")
        ttk.Button(btns, text="Apply", command=self._apply).pack(side="right", padx=4)

    def _collect(self) -> dict:
        out = {}
        for k, var in self._vars.items():
            try:
                out[k] = var.get()
            except tk.TclError:
                pass
        out["alpha"] = max(0.2, min(1.0, float(out.get("alpha", 1.0))))
        out["tint_alpha"] = max(0, min(255, int(out.get("tint_alpha", 170))))
        out["font_scale"] = max(0.6, min(2.5, float(out.get("font_scale", 1.0))))
        out["width"] = max(MIN_WIDTH, int(out.get("width", 320)))
        out["height"] = max(MIN_HEIGHT, int(out.get("height", 170)))
        out["refresh_seconds"] = max(5, int(out.get("refresh_seconds", 30)))
        return out

    def _apply(self):
        self.owner.apply_settings(self._collect())
        self.win.destroy()

    def _reset(self):
        self.owner.apply_settings(dict(DEFAULTS))
        self.win.destroy()


if __name__ == "__main__":
    import auth
    import first_run
    cfg = load_config()
    cfg = first_run.maybe_run(cfg)
    save_config(cfg)
    auth.set_credentials_path(cfg.get("credentials_path"))
    Widget().run()
