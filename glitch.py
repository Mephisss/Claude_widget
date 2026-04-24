"""VHS-style glitch overlay for a tk Canvas (open / close transitions)."""
from __future__ import annotations

import random
from typing import Callable

import tkinter as tk

GLITCH_COLORS = ("#ff2bd6", "#2bf0ff", "#ffffff", "#cc785c", "#ff5e3a")
SCAN_COLOR = "#000000"


def _draw_frame(canvas: tk.Canvas, w: int, h: int, intensity: float,
                accent: str) -> list[int]:
    ids: list[int] = []
    if intensity <= 0:
        return ids

    n_bars = int(2 + intensity * 6)
    for _ in range(n_bars):
        y = random.randint(0, h)
        bar_h = random.randint(2, max(3, int(4 + intensity * 6)))
        shift = random.randint(-int(intensity * 22), int(intensity * 22))
        color = random.choice(GLITCH_COLORS + (accent,))
        stipple = random.choice(("gray12", "gray25", "gray50"))
        ids.append(
            canvas.create_rectangle(
                shift, y, w + shift, y + bar_h,
                fill=color, outline="", stipple=stipple,
            )
        )

    for _ in range(int(intensity * 4)):
        y = random.randint(0, h)
        ids.append(canvas.create_line(0, y, w, y, fill=SCAN_COLOR))

    for _ in range(int(intensity * 5)):
        bx = random.randint(0, w - 6)
        by = random.randint(0, h - 6)
        bw = random.randint(2, 8)
        bh = random.randint(2, 6)
        color = random.choice(GLITCH_COLORS)
        ids.append(canvas.create_rectangle(bx, by, bx + bw, by + bh,
                                            fill=color, outline=""))
    return ids


def animate(canvas: tk.Canvas, root: tk.Misc, *,
            mode: str = "in",
            duration_ms: int = 420,
            frames: int = 14,
            accent: str = "#cc785c",
            on_each_frame: Callable[[float], None] | None = None,
            on_done: Callable[[], None] | None = None,
            redraw: Callable[[], None] | None = None) -> None:
    """mode='in': intensity fades 1→0. mode='out': intensity grows 0→1."""
    if redraw is not None:
        redraw()

    interval = max(20, duration_ms // frames)
    state = {"frame": 0, "ids": []}

    def _clear_overlay():
        for i in state["ids"]:
            try:
                canvas.delete(i)
            except tk.TclError:
                pass
        state["ids"] = []

    def step():
        try:
            w = canvas.winfo_width()
            h = canvas.winfo_height()
        except tk.TclError:
            if on_done:
                on_done()
            return

        _clear_overlay()
        f = state["frame"]
        if f >= frames:
            if on_done:
                on_done()
            return

        if mode == "in":
            intensity = (frames - f) / frames
        else:
            intensity = (f + 1) / frames

        state["ids"] = _draw_frame(canvas, w, h, intensity, accent)
        if on_each_frame is not None:
            on_each_frame(intensity)
        state["frame"] += 1
        root.after(interval, step)

    step()
