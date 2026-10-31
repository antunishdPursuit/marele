"""Title and morning screens: the painted backgrounds, ready for the browser.

The two backgrounds (assets/concept-art/BG - Home.png, BG - Ending.png) are
painted with OpenAI image generation, with no text in them (the home one shows
Marycel at the computer). The game draws the title on the monitor and the
buttons on top, so the art and the interface stay separate. This script saves them as JPEGs in
assets/screens/ and prints where the monitor's glass is, for game.js (HOME).

    .venv/Scripts/python tools/build_screens.py
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from pixel_spec import CONCEPT, ROOT

OUT = ROOT / "assets" / "screens"
SOURCES = {"home": "BG - Home with Marycel B.png", "ending": "BG - Ending.png"}


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


if __name__ == "__main__":
    main()
