"""Shared pixel-art rules for Marele.

Every game asset is authored at native size: one art pixel is one pixel of the
640x360 game screen. Nothing is resized inside the game; the whole screen is
enlarged by a whole number (2x = 1280x720, 3x = 1920x1080) with nearest-
neighbour sampling. All assets use the one shared palette built here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CONCEPT = ROOT / "assets" / "concept-art"
PIXEL_OUT = ROOT / "assets" / "pixel"

SCREEN = (640, 360)
ROOM_SIZE = (960, 224)  # every room background: 1.5 screens wide, the view scrolls
CHARACTER_HEIGHT = 110  # Marycel standing, head to sole (~80% of door height)
DISPLAY_SCALES = (2, 3)

# The generated room images are references only; rooms are drawn by
# build_rooms.py with the ramps below.
ROOM_REFERENCES = {
    "repair-shop": "Family Repair Shop - Matched Background.png",
    "electronics-workshop": "Electronics Workshop - Matched Background.png",
    "home-workshop": "Family Home Workshop - Matched Background.png",
}
CHARACTER_SOURCES = [
    "Marycel - Star Sweater Character Sheet.png",
    "Hacktoberfest Week 4 - Marycel Character Concept.png",
]

# Hand-picked room ramps, dark to light. No colour appears in two ramps, so a
# pixel can be shaded one step lighter or darker within its own ramp.
ROOM_RAMPS = {
    "ink": [(12, 8, 10)],
    "warm_wood": [(40, 20, 10), (70, 36, 16), (104, 54, 22), (140, 76, 32), (176, 102, 46), (212, 136, 70)],
    "grey_brown": [(26, 22, 24), (40, 34, 34), (56, 48, 46), (74, 64, 60), (94, 82, 74), (118, 104, 92)],
    "metal": [(30, 30, 36), (48, 48, 56), (76, 76, 86), (112, 112, 120)],
    "red_wood": [(34, 16, 14), (56, 26, 22), (80, 40, 32), (106, 56, 42), (136, 76, 56)],
    "mauve": [(78, 46, 54), (98, 60, 68), (120, 76, 84), (144, 96, 102)],
    "rose": [(104, 30, 44), (150, 48, 62), (186, 80, 88)],
    "green": [(20, 34, 28), (34, 54, 42), (52, 78, 58), (72, 100, 74)],
    "night": [(4, 8, 24), (8, 16, 44), (14, 28, 74), (26, 46, 112), (46, 70, 150)],
    "star": [(210, 224, 250)],
    "lamp": [(150, 80, 24), (232, 170, 70), (255, 226, 140)],
    "brass": [(110, 70, 24), (186, 132, 52), (236, 196, 110)],
}
CHARACTER_COLOURS = 20
# Hand-picked colours for code-drawn props (plastic, CRT phosphor, paper).
PROP_COLOURS = [
    (226, 214, 184), (190, 176, 146), (140, 126, 102), (92, 80, 66),
    (24, 32, 28), (64, 196, 112), (34, 110, 66), (244, 240, 226),
]

PALETTE_PNG = PIXEL_OUT / "palette.png"
PALETTE_GPL = PIXEL_OUT / "palette.gpl"


# ------------------------------------------------------------------ helpers


def _median_cut(pixels: np.ndarray, n: int) -> np.ndarray:
    strip = Image.fromarray(pixels.reshape(1, -1, 3).astype(np.uint8))
    q = strip.quantize(colors=n, method=Image.Quantize.MEDIANCUT, kmeans=4)
    return np.array(q.getpalette()[: n * 3], np.uint8).reshape(-1, 3)


def _character_pixels() -> np.ndarray:
    out = []
    for name in CHARACTER_SOURCES:
        sheet = Image.open(CONCEPT / name).convert("RGBA")
        # Sheets are ~620 px per figure; shrink to near native so the palette
        # sees the colours that survive at game size.
        f = CHARACTER_HEIGHT / 620
        small = np.asarray(sheet.resize((round(sheet.width * f), round(sheet.height * f)), Image.BOX))
        out.append(small[small[..., 3] > 200][:, :3])
    return np.concatenate(out)


def build_palette() -> np.ndarray:
    colours = np.concatenate([
        np.array([c for ramp in ROOM_RAMPS.values() for c in ramp], np.uint8),
        _median_cut(_character_pixels(), CHARACTER_COLOURS),
        np.array(PROP_COLOURS, np.uint8),
    ])
    colours = np.unique(colours, axis=0)
    order = np.argsort(colours.astype(np.int32) @ np.array([299, 587, 114]))
    return colours[order]


def save_palette(colours: np.ndarray) -> None:
    PIXEL_OUT.mkdir(parents=True, exist_ok=True)
    swatch = Image.fromarray(colours.reshape(1, -1, 3)).resize((len(colours) * 8, 8), Image.NEAREST)
    swatch.save(PALETTE_PNG)
    lines = ["GIMP Palette", "Name: Marele", "Columns: 8", "#"]
    lines += [f"{r:3d} {g:3d} {b:3d}\t#{r:02x}{g:02x}{b:02x}" for r, g, b in colours]
    PALETTE_GPL.write_text("\n".join(lines) + "\n")


def load_palette() -> np.ndarray:
    if not PALETTE_PNG.exists():
        save_palette(build_palette())
    sw = np.asarray(Image.open(PALETTE_PNG).convert("RGB"))
    return sw[0, ::8]


# ------------------------------------------------------------ quantizing


def nearest(colours: np.ndarray, rgb) -> tuple[int, int, int]:
    d = ((colours.astype(np.int32) - np.array(rgb, np.int32)) ** 2).sum(-1)
    return tuple(int(v) for v in colours[d.argmin()])


def quantize(img: Image.Image, colours: np.ndarray, alpha_cut: int = 128) -> Image.Image:
    """Snap every pixel to the palette (no dithering) and make alpha 0 or 255."""
    rgba = np.asarray(img.convert("RGBA"))
    pal_img = Image.new("P", (1, 1))
    flat = colours.reshape(-1).tolist()
    pal_img.putpalette(flat + flat[:3] * (256 - len(colours)))
    q = img.convert("RGB").quantize(palette=pal_img, dither=Image.Dither.NONE).convert("RGB")
    out = np.dstack([np.asarray(q), np.where(rgba[..., 3] >= alpha_cut, 255, 0).astype(np.uint8)])
    out[out[..., 3] == 0, :3] = 0
    return Image.fromarray(out)


def check(img: Image.Image, colours: np.ndarray) -> list[str]:
    """Return rule violations for a native asset (empty list means it passes)."""
    a = np.asarray(img.convert("RGBA"))
    problems = []
    partial = ((a[..., 3] > 0) & (a[..., 3] < 255)).sum()
    if partial:
        problems.append(f"{partial} semi-transparent pixels")
    opaque = a[a[..., 3] == 255][:, :3]
    pal = {tuple(c) for c in colours.tolist()}
    used = {tuple(c) for c in np.unique(opaque, axis=0).tolist()}
    off = used - pal
    if off:
        problems.append(f"{len(off)} colours outside the palette")
    return problems
