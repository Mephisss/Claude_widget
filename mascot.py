"""Generate the Claude pixel-art mascot at any size, no asset files needed."""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

ORANGE = (204, 120, 92, 255)
ORANGE_DARK = (148, 78, 56, 255)
EYE = (28, 22, 20, 255)
HIGHLIGHT = (240, 168, 132, 255)
SHADOW = (110, 58, 42, 255)
TRANSPARENT = (0, 0, 0, 0)

_GRID = [
    "................",
    "................",
    "................",
    "....AAAAAAAA....",
    "...AHAAAAAAA....",
    "..AHAAAAAAAAA...",
    "..AAEEAAAAEEAA..",
    "..AAEEAAAAEEAA..",
    "..AAAAAAAAAAAA..",
    "..AAAAAAAAAAAA..",
    "..AAAAAAAAAAAA..",
    "..ASAAASSSAAASA.",
    "..A.A.A...A.A.A.",
    "....A.A...A.A...",
    "................",
    "................",
]
_COLORS = {"A": ORANGE, "H": HIGHLIGHT, "S": SHADOW, "E": EYE}


@lru_cache(maxsize=8)
def build(size: int = 64) -> Image.Image:
    if size < 16:
        size = 16
    cell = size // 16
    img_size = cell * 16
    img = Image.new("RGBA", (img_size, img_size), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    for y, row in enumerate(_GRID):
        for x, ch in enumerate(row):
            c = _COLORS.get(ch)
            if c:
                draw.rectangle(
                    [x * cell, y * cell, (x + 1) * cell - 1, (y + 1) * cell - 1],
                    fill=c,
                )
    if img_size != size:
        img = img.resize((size, size), Image.NEAREST)
    return img


def to_ico_bytes() -> bytes:
    import io
    buf = io.BytesIO()
    base = build(64)
    base.save(buf, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    return buf.getvalue()


if __name__ == "__main__":
    build(256).save("mascot_preview.png")
    print("wrote mascot_preview.png")
