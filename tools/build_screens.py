"""Title and morning screens: the painted backgrounds, ready for the browser.

The two backgrounds (assets/concept-art/BG - Home.png, BG - Ending.png) are
painted with OpenAI image generation, with no text in them (the home one shows
Marycel at the computer). The game draws the title on the monitor and the
buttons on top, so the art and the interface stay separate. This script saves them as JPEGs in
assets/screens/ and prints where the monitor's glass is, for game.js (HOME).

The four How to play pictures come from one generated sheet (UI - How to Play Icons.png)
and are cut into a single 4x1 strip, how-icons.png.

    .venv/Scripts/python tools/build_screens.py
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from pixel_spec import CONCEPT, ROOT

OUT = ROOT / "assets" / "screens"
SOURCES = {"home": "BG - Home with Marycel B.png", "ending": "BG - Ending.png"}
ICONS = "UI - How to Play Icons.png"
# centre x, centre y and square size of each picture: rooms, computer, answer, Echo
ICON_BOXES = [(252, 490, 410), (645, 500, 360), (978, 500, 360), (1335, 500, 380)]
ICON_SIZE = 128


def crt_glass(img: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the green monitor glass in the middle of the home scene."""
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    green = (g > r + 30) & (g > b + 10)
    w = a.shape[1]
    green[:, : w // 4] = False
    green[:, w * 3 // 4 :] = False
    rows, cols = green.sum(1), green.sum(0)
    ys = np.nonzero(rows > rows.max() * 0.5)[0]
    xs = np.nonzero(cols > cols.max() * 0.5)[0]
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, file in SOURCES.items():
        img = Image.open(CONCEPT / file).convert("RGB")
        dest = OUT / f"{name}.jpg"
        img.save(dest, quality=88, optimize=True, progressive=True)
        print(f"{name}: {img.size[0]}x{img.size[1]}, {dest.stat().st_size // 1024} KB")
        if name == "home":
            print("  monitor glass:", crt_glass(img))
    sheet = Image.open(CONCEPT / ICONS).convert("RGB")
    strip = Image.new("RGB", (ICON_SIZE * len(ICON_BOXES), ICON_SIZE))
    for i, (x, y, size) in enumerate(ICON_BOXES):
        h = size // 2
        tile = sheet.crop((x - h, y - h, x + h, y + h)).resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
        strip.paste(tile, (i * ICON_SIZE, 0))
    dest = OUT / "how-icons.png"
    strip.save(dest, optimize=True)
    print(f"icons: {strip.size[0]}x{strip.size[1]}, {dest.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
