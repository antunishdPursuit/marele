"""Draw the three room backgrounds as native pixel art (960x224).

Rooms are 1.5 screens wide; the game view (640 px) scrolls to follow Marycel.

The generated images in assets/concept-art are references only. Every pixel
here is placed by code on the shared grid, using the hand-picked ramps in
pixel_spec.ROOM_RAMPS. The rooms share one shell (beamed ceiling, back wall in
four bays, two side walls, window, door, plank floor) and differ in materials.

    .venv/Scripts/python tools/build_rooms.py   # writes assets/pixel/rooms/
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

import pixel_spec as ps

W, H = ps.ROOM_SIZE
CEIL_Y, FLOOR_Y = 30, 162  # back wall top and bottom rows
LEFT_X, RIGHT_X = 70, W - 74  # back corners
FRONT_BOTTOM_LEFT, FRONT_BOTTOM_RIGHT = 184, 188  # side walls meet the floor at the frame edge
VP = ((LEFT_X + RIGHT_X) // 2, 96)  # vanishing point for the ceiling beams
BAY = (RIGHT_X - LEFT_X) // 4
PILLARS = tuple(LEFT_X + BAY * i for i in range(4)) + (RIGHT_X,)
WINDOW = (PILLARS[2] + 24, 40, PILLARS[3] - 24, 112)  # glass in the third bay: x0, y0, x1, y1
DOOR_X = (W - 56, W - 20)  # door columns on the right wall
DOOR_FRACTION = 0.86  # share of the wall height the door fills
RAIL_Y = 118  # home-workshop chair rail on the back wall

R = ps.ROOM_RAMPS
INK = R["ink"][0]

ROOMS = {
    "repair-shop": dict(seed=11, wall="wood", wall_ramp="warm_wood", trim="warm_wood",
                        pillar="wood", ceiling="warm_wood", floor="warm_wood"),
    "electronics-workshop": dict(seed=22, wall="plaster", wall_ramp="grey_brown", trim="grey_brown",
                                 pillar="metal", ceiling="grey_brown", floor="grey_brown"),
    "home-workshop": dict(seed=33, wall="wallpaper", wall_ramp="mauve", trim="red_wood",
                          pillar="wood", ceiling="red_wood", floor="red_wood"),
}

# ------------------------------------------------------------------ geometry

_xs = np.arange(W)
_t_left = np.clip((LEFT_X - _xs) / LEFT_X, 0, 1)
_t_right = np.clip((_xs - RIGHT_X) / (W - 1 - RIGHT_X), 0, 1)
TOP_F = CEIL_Y * (1 - _t_left - _t_right)  # wall top per column (float)
BOT_F = FLOOR_Y + (FRONT_BOTTOM_LEFT - FLOOR_Y) * _t_left + (FRONT_BOTTOM_RIGHT - FLOOR_Y) * _t_right
TOP = np.round(TOP_F).astype(int)
BOT = np.round(BOT_F).astype(int)
YY = np.arange(H)[:, None]
XX = _xs[None, :]
WALL = (YY >= TOP) & (YY < BOT)
CEIL = YY < TOP
FLOOR = YY >= BOT
BACK = WALL & (XX >= LEFT_X) & (XX <= RIGHT_X)
SIDES = WALL & ~BACK


def wall_row(x: int, yb: float) -> float:
    """Row at column x that matches back-wall row yb (follows the perspective)."""
    return TOP_F[x] + (yb - CEIL_Y) / (FLOOR_Y - CEIL_Y) * (BOT_F[x] - TOP_F[x])


def side_edges(n: int) -> tuple[list[int], list[int]]:
    """Board boundaries on the side walls, wider toward the viewer."""
    left = sorted({round(LEFT_X * (1 - (k / n) ** 1.4)) for k in range(n + 1)})
    right = sorted({round(RIGHT_X + 1 + (W - 1 - RIGHT_X) * (k / n) ** 1.4) for k in range(n + 1)})
    return left, right


def checker(offset: int = 0) -> np.ndarray:
    return (YY + XX + offset) % 2 == 0


# ------------------------------------------------------------------ canvas


class Canvas:
    """Room image as an array; every colour written is a palette colour."""

    def __init__(self, colours: np.ndarray, seed: int):
        self.colours = colours
        self.rng = np.random.default_rng(seed)
        self.a = np.zeros((H, W, 3), np.uint8)
        self._lut = {}
        for ramp in R.values():
            snapped = [self.c(c) for c in ramp]
            for i, c in enumerate(snapped):
                for d in (-1, 1):
                    self._lut[(c, d)] = snapped[min(max(i + d, 0), len(snapped) - 1)]

    def c(self, rgb) -> tuple[int, int, int]:
        return ps.nearest(self.colours, rgb)

    def put(self, mask, rgb) -> None:
        self.a[mask] = self.c(rgb)

    def rect(self, x0, y0, x1, y1, rgb, clip=None) -> None:
        m = (XX >= x0) & (XX <= x1) & (YY >= y0) & (YY <= y1)
        self.put(m if clip is None else m & clip, rgb)

    def px(self, x, y, rgb) -> None:
        if 0 <= x < W and 0 <= y < H:
            self.a[y, x] = self.c(rgb)

    def mask(self, draw) -> np.ndarray:
        m = Image.new("1", (W, H))
        draw(ImageDraw.Draw(m))
        return np.asarray(m)

    def poly(self, pts, rgb, clip=None) -> None:
        m = self.mask(lambda d: d.polygon(pts, fill=1))
        self.put(m if clip is None else m & clip, rgb)

    def line(self, pts, rgb, width=1, clip=None) -> None:
        m = self.mask(lambda d: d.line(pts, fill=1, width=width))
        self.put(m if clip is None else m & clip, rgb)

    def shift(self, mask, d: int) -> None:
        """Move masked pixels one step lighter (+1) or darker (-1) in their ramp."""
        sub = self.a[mask]
        out = sub.copy()
        for c in np.unique(sub, axis=0):
            key = (tuple(int(v) for v in c), d)
            if key in self._lut:
                out[(sub == c).all(-1)] = self._lut[key]
        self.a[mask] = out

    def stamp(self, pattern, x, y, inks, clip) -> None:
        for dy, row in enumerate(pattern):
            for dx, ch in enumerate(row):
                if ch in inks and 0 <= x + dx < W and 0 <= y + dy < H and clip[y + dy, x + dx]:
                    self.a[y + dy, x + dx] = self.c(inks[ch])


def smooth_noise(rng, cell: int) -> np.ndarray:
    small = rng.random((H // cell + 3, W // cell + 3)).astype(np.float32)
    big = Image.fromarray(small, "F").resize((small.shape[1] * cell, small.shape[0] * cell), Image.BILINEAR)
    return np.asarray(big)[cell: cell + H, cell: cell + W]


# ------------------------------------------------------------------ surfaces


def boards(cv: Canvas, region, ramp, edges, base=2, grain=True) -> None:
    """Vertical boards between the given x edges, clipped to region."""
    for x0, x1 in zip(edges, edges[1:]):
        shade = base + (1 if cv.rng.random() < 0.25 else 0)
        cols = (XX >= x0) & (XX < x1)
        cv.put(region & cols, ramp[shade])
        cv.put(region & (XX == x0), ramp[base - 1])
        if x1 - x0 >= 4:
            cv.put(region & (XX == x0 + 1), ramp[min(shade + 1, len(ramp) - 1)])
        if grain and x1 - x0 >= 5:
            rows = np.nonzero(region[:, min(x0 + 2, W - 1)])[0]
            if len(rows) < 12:
                continue
            for _ in range(int(cv.rng.integers(1, 4))):
                gx = int(cv.rng.integers(x0 + 2, x1 - 1))
                gy = int(cv.rng.integers(rows.min(), rows.max() - 6))
                length = int(cv.rng.integers(4, 15))
                cv.put(region & (XX == gx) & (YY >= gy) & (YY < gy + length), ramp[shade - 1])


def wall_edges(width: int) -> list[list[int]]:
    left, right = side_edges(9)
    return [left, list(range(LEFT_X, RIGHT_X + 1, width)) + [RIGHT_X + 1], right]


def wood_wall(cv: Canvas, region, ramp) -> None:
    for edges in wall_edges(7):
        boards(cv, region, ramp, edges)


def plaster_wall(cv: Canvas, region, ramp) -> None:
    cv.put(region, ramp[2])
    v = 0.65 * smooth_noise(cv.rng, 14) + 0.35 * smooth_noise(cv.rng, 5)
    cv.put(region & (v > 0.7), ramp[3])
    cv.put(region & (v < 0.27), ramp[1])
    # Water streaks running down from the top.
    for _ in range(26):
        x = int(cv.rng.integers(0, W))
        y0 = TOP[x] + int(cv.rng.integers(2, 30))
        length = int(cv.rng.integers(6, 30))
        cv.put(region & (XX == x) & (YY >= y0) & (YY < y0 + length), ramp[1])


ROSE_MOTIF = [
    ".rr.",
    "rRRr",
    "rRrr",
    ".rr.",
    ".g..",
    "lgl.",
    ".g..",
]
SPRIG = ["x.x", ".x.", "x.x"]


def wallpaper_wall(cv: Canvas, region, ramp) -> None:
    cv.put(region, ramp[2])
    inks = {"r": R["rose"][0], "R": R["rose"][1], "g": R["green"][1], "l": R["green"][2]}
    for row, y in enumerate(range(CEIL_Y + 4, FLOOR_Y, 24)):
        off = 12 if row % 2 else 0
        for x in range(off - 4, W, 24):
            cv.stamp(ROSE_MOTIF, x, y, inks, region)
            cv.stamp(SPRIG, x + 12, y + 12, {"x": ramp[1]}, region)
    # Wainscot: dark boards below a chair rail that follows the perspective.
    rail = np.array([wall_row(x, RAIL_Y) for x in range(W)])
    below = WALL & (YY >= np.round(rail).astype(int))
    for edges in wall_edges(8):
        boards(cv, below, R["red_wood"], edges, base=1, grain=False)
    for x in range(W):
        if WALL[:, x].any():
            y = round(rail[x])
            cv.px(x, y - 2, R["red_wood"][3])
            cv.px(x, y - 1, R["red_wood"][2])
            cv.px(x, y, R["red_wood"][0])


def baseboard(cv: Canvas, ramp, height=5, base=1) -> None:
    for x in range(W):
        if not WALL[:, x].any():
            continue
        h = max(2, round(height * (BOT_F[x] - TOP_F[x]) / (FLOOR_Y - CEIL_Y)))
        cv.rect(x, BOT[x] - h, x, BOT[x] - 1, ramp[base])
        cv.px(x, BOT[x] - h, ramp[base + 1])


def wood_pillar(cv: Canvas, x, ramp) -> None:
    cv.rect(x - 5, CEIL_Y - 1, x + 4, FLOOR_Y, ramp[2])
    cv.rect(x - 5, CEIL_Y - 1, x - 5, FLOOR_Y, ramp[0])
    cv.rect(x - 4, CEIL_Y - 1, x - 4, FLOOR_Y, ramp[3])
    cv.rect(x + 3, CEIL_Y - 1, x + 3, FLOOR_Y, ramp[1])
    cv.rect(x + 4, CEIL_Y - 1, x + 4, FLOOR_Y, ramp[0])
    cv.rect(x - 6, FLOOR_Y - 7, x + 5, FLOOR_Y, ramp[1])  # plinth
    cv.rect(x - 6, FLOOR_Y - 7, x + 5, FLOOR_Y - 7, ramp[3])


def metal_pillar(cv: Canvas, x, ramp) -> None:
    m, b = R["metal"], R["brass"]
    cv.rect(x - 5, CEIL_Y - 1, x + 4, FLOOR_Y, m[1])
    cv.rect(x - 5, CEIL_Y - 1, x - 5, FLOOR_Y, m[0])
    cv.rect(x - 4, CEIL_Y - 1, x - 4, FLOOR_Y, m[2])
    cv.rect(x + 4, CEIL_Y - 1, x + 4, FLOOR_Y, m[0])
    for y0, y1 in ((86, 97), (FLOOR_Y - 10, FLOOR_Y)):
        cv.rect(x - 7, y0, x + 6, y1, m[2])
        cv.rect(x - 7, y1, x + 6, y1, m[0])
        cv.rect(x - 7, y0, x - 7, y1, m[3])
        for bx, by in ((x - 5, y0 + 2), (x + 4, y0 + 2), (x - 5, y1 - 2), (x + 4, y1 - 2)):
            cv.px(bx, by, b[1])


def conduit(cv: Canvas) -> None:
    """Electrical conduit on the electronics-workshop walls."""
    m, b = R["metal"], R["brass"]
    y = CEIL_Y + 8
    for x0, x1 in ((PILLARS[0] + 14, PILLARS[1] - 8), (PILLARS[1] + 12, PILLARS[2] - 8)):
        cv.rect(x0, y, x1, y, m[3])
        cv.rect(x0, y + 1, x1, y + 1, m[1])
        for bx in (x0, x1 - 5):
            cv.rect(bx, y - 2, bx + 5, y + 3, m[2])
            cv.rect(bx, y + 3, bx + 5, y + 3, m[0])
            cv.px(bx + 2, y, b[1])
    for x in (18, RIGHT_X - 9):  # vertical runs
        top, bot = TOP[x] + 3, BOT[x] - 6
        cv.rect(x, top, x, bot, m[3])
        cv.rect(x + 1, top, x + 1, bot, m[1])
        box = round(wall_row(x, 100))
        cv.rect(x - 3, box, x + 4, box + 9, m[2])
        cv.rect(x - 3, box + 9, x + 4, box + 9, m[0])
        cv.px(x, box + 4, b[1])


# ------------------------------------------------------------------ ceiling


def ceiling(cv: Canvas, ramp) -> None:
    cv.put(CEIL, ramp[1])
    rows = (3, 10, 17, 23)
    for y in rows:
        cv.put(CEIL & (YY == y), ramp[0])
    for y0, y1 in zip((0,) + rows, rows + (30,)):  # board joints
        for x in cv.rng.integers(0, W, 9):
            cv.put(CEIL & (XX == x) & (YY > y0) & (YY < y1), ramp[0])
    k = VP[1] / (VP[1] - 24)
    for xb in [x + BAY // 2 * j for x in PILLARS[:4] for j in (0, 1)][1:]:
        xf = VP[0] + (xb - VP[0]) * k
        cv.poly([(xb - 3, 24), (xb + 3, 24), (xf + 5, -1), (xf - 5, -1)], ramp[2])
        cv.line([(xb - 3, 24), (xf - 5, -1)], ramp[3] if xb > VP[0] else ramp[0])
        cv.line([(xb + 3, 24), (xf + 5, -1)], ramp[0] if xb > VP[0] else ramp[3])
    # Beams along the tops of the side walls and the back wall.
    cv.line([(LEFT_X, CEIL_Y - 3), (0, -3)], ramp[2], width=5)
    cv.line([(RIGHT_X, CEIL_Y - 3), (W - 1, -3)], ramp[2], width=5)
    cv.rect(LEFT_X - 6, 24, RIGHT_X + 6, 29, ramp[2])
    cv.rect(LEFT_X - 6, 24, RIGHT_X + 6, 24, ramp[3])
    cv.rect(LEFT_X - 6, 29, RIGHT_X + 6, 29, ramp[0])


# ------------------------------------------------------------------ window


def pine(cv: Canvas, cx, base, height, half, rgb, clip) -> None:
    top = base - height
    tier = max(4, height // 4)
    for y in range(top, base):
        f = (y - top) / height
        hw = half * f * (0.55 + 0.45 * ((y - top) % tier) / tier)
        cv.rect(round(cx - hw), y, round(cx + hw), y, rgb, clip)
    cv.rect(cx, base, cx, base + 3, rgb, clip)


def night_scene(cv: Canvas, x0, y0, x1, y1) -> None:
    n = R["night"]
    glass = (XX >= x0) & (XX <= x1) & (YY >= y0) & (YY <= y1)
    h = y1 - y0
    bands = [(0.0, n[1]), (0.38, n[2]), (0.72, n[3])]
    for i, (start, rgb) in enumerate(bands):
        ys = y0 + round(start * h)
        cv.put(glass & (YY >= ys), rgb)
        if i:  # two dithered rows soften each band edge
            cv.put(glass & ((YY == ys) | (YY == ys + 1)) & checker(), bands[i - 1][1])
    for _ in range(16):
        sx = int(cv.rng.integers(x0 + 2, x1 - 1))
        sy = int(cv.rng.integers(y0 + 2, y0 + h // 2))
        cv.px(sx, sy, R["star"][0] if cv.rng.random() < 0.5 else n[4])
    # Distant tree line.
    phase = cv.rng.random() * 6
    for x in range(x0, x1 + 1):
        ridge = y1 - 12 - 3 * math.sin(x / 9 + phase) - 2 * math.sin(x / 4.3)
        cv.rect(x, round(ridge), x, y1, n[1], glass)
    # Neighbour's house with lit windows, centre pane.
    hx, hb = x0 + (x1 - x0) // 2 - 12 + int(cv.rng.integers(-8, 9)), y1 - 4
    cv.rect(hx, hb - 14, hx + 26, hb, n[0], glass)
    cv.poly([(hx - 3, hb - 14), (hx + 13, hb - 26), (hx + 29, hb - 14)], n[0], glass)
    cv.rect(hx + 19, hb - 25, hx + 21, hb - 19, n[0], glass)  # chimney
    for wx in (hx + 5, hx + 15):
        cv.rect(wx, hb - 10, wx + 4, hb - 6, R["lamp"][1])
        cv.rect(wx + 2, hb - 10, wx + 2, hb - 6, R["lamp"][0])
        cv.rect(wx, hb - 8, wx + 4, hb - 8, R["lamp"][0])
        cv.px(wx, hb - 10, R["lamp"][2])
    # Power pole and sagging wires.
    px_ = x0 + round((x1 - x0) * (0.7 + 0.1 * cv.rng.random()))
    cv.rect(px_, y1 - 46, px_, y1, n[0], glass)
    cv.rect(px_ - 5, y1 - 42, px_ + 5, y1 - 42, n[0], glass)
    for tx, ty in ((x0 - 2, y1 - 52), (x1 + 2, y1 - 36)):
        pts = [(px_ + (tx - px_) * s, y1 - 42 + (ty - y1 + 42) * s + 6 * s * (1 - s) * 2) for s in np.linspace(0, 1, 24)]
        cv.line(pts, n[0], clip=glass)
    # Pines in front, left and right panes.
    for cx, height, half in ((x0 + 14, 52, 11), (x0 + 30, 34, 7), (x1 - 16, 60, 13), (x1 - 38, 38, 8)):
        pine(cv, cx, y1 - 2, height, half, n[0], glass)


def window(cv: Canvas, ramp) -> None:
    x0, y0, x1, y1 = WINDOW
    cv.rect(x0 - 5, y0 - 5, x1 + 5, y1 + 4, ramp[1])
    cv.rect(x0 - 5, y0 - 5, x1 + 5, y0 - 5, ramp[3])
    cv.rect(x0 - 5, y0 - 5, x0 - 5, y1 + 4, ramp[2])
    cv.rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1, INK)
    night_scene(cv, x0, y0, x1, y1)
    for mx in (x0 + round((x1 - x0) * 0.28), x1 - round((x1 - x0) * 0.28)):
        cv.rect(mx - 1, y0, mx + 1, y1, ramp[1])
        cv.rect(mx - 2, y0, mx - 2, y1, INK)
        cv.rect(mx + 2, y0, mx + 2, y1, INK)
        cv.rect(mx - 1, y0 + 32, mx - 1, y0 + 35, R["brass"][1])  # latch
    cv.rect(x0 - 9, y1 + 4, x1 + 9, y1 + 8, ramp[2])
    cv.rect(x0 - 9, y1 + 4, x1 + 9, y1 + 4, ramp[4])
    cv.rect(x0 - 9, y1 + 8, x1 + 9, y1 + 8, ramp[0])
    cv.rect(x0 - 7, y1 + 9, x1 + 7, y1 + 9, ramp[1])  # shadow under the sill


# ------------------------------------------------------------------ door


def door(cv: Canvas, trim) -> None:
    g, b, n = R["green"], R["brass"], R["night"]
    d0, d1 = DOOR_X
    for x in range(d0 - 3, d1 + 4):
        bot = BOT_F[x]
        top = bot - DOOR_FRACTION * (bot - TOP_F[x])
        cv.rect(x, round(top) - 3, x, BOT[x] - 1, trim[1] if x in (d0 - 3, d1 + 3) else trim[2])
        cv.px(x, round(top) - 3, trim[3])
        if not d0 <= x <= d1:
            continue
        u = (x - d0) / (d1 - d0)
        for y in range(round(top), BOT[x]):
            v = (y - top) / (bot - top)
            rgb = g[2]
            if 0.28 <= u <= 0.8 and 0.08 <= v <= 0.44:  # glass
                rgb = n[2] if v < 0.24 else n[1]
                if (u < 0.31 or u > 0.77 or v < 0.1 or v > 0.42):
                    rgb = g[0]
            elif 0.24 <= u <= 0.84 and 0.55 <= v <= 0.9:  # lower panel
                edge = u < 0.28 or u > 0.8 or v < 0.57 or v > 0.88
                rgb = g[1] if edge else g[2]
            if x == d0:
                rgb = g[3]
            elif x == d1:
                rgb = g[0]
            cv.px(x, y, rgb)
    # Brass handle near the left edge.
    hx = d0 + 3
    top = BOT_F[hx] - DOOR_FRACTION * (BOT_F[hx] - TOP_F[hx])
    hy = round(top + 0.52 * (BOT_F[hx] - top))
    cv.rect(hx, hy - 4, hx + 1, hy + 3, b[1])
    cv.rect(hx + 2, hy - 1, hx + 4, hy, b[1])
    cv.px(hx, hy - 4, b[2])
    cv.px(hx + 1, hy + 3, b[0])


# ------------------------------------------------------------------ floor


def floor(cv: Canvas, ramp, base=2) -> None:
    ys, step = [FLOOR_Y], 3.0
    while ys[-1] < H:
        ys.append(round(ys[-1] + step))
        step *= 1.27
    for ya, yb in zip(ys, ys[1:]):
        h = yb - ya
        band = FLOOR & (YY >= ya) & (YY < yb)
        x = -int(cv.rng.integers(0, 80))
        while x < W:
            length = int(cv.rng.integers(70, 150) * (0.6 + h / 10))
            shade = base + (cv.rng.random() < 0.3) - (cv.rng.random() < 0.15)
            plank = band & (XX >= x) & (XX < x + length)
            cv.put(plank, ramp[shade])
            if h >= 6:
                cv.put(plank & (YY == ya + 1), ramp[shade + 1])
            cv.put(band & (XX == x), ramp[base - 1])
            if h >= 5:  # nail heads either side of the joint
                for nx in (x - 2, x + 2):
                    cv.put(band & (XX == nx) & (YY == ya + h // 2), ramp[base - 1])
            x += length
        cv.put(band & (YY == ya), ramp[base - 1])
    # Scuffs and worn patches.
    for _ in range(40):
        sx, sy = int(cv.rng.integers(0, W)), int(cv.rng.integers(FLOOR_Y + 8, H - 4))
        length = int(cv.rng.integers(3, 10))
        cv.shift(FLOOR & (YY == sy) & (XX >= sx) & (XX < sx + length), 1 if cv.rng.random() < 0.6 else -1)
    # Moonlight from the window falls forward across the floor; the mullions
    # cast two dark bars through it.
    x0, _, x1, _ = WINDOW
    lean = 34
    shaft = cv.mask(lambda d: d.polygon([(x0 + 6, FLOOR_Y + 1), (x1 - 6, FLOOR_Y + 1),
                                         (x1 - 6 + lean, H - 1), (x0 + 6 + lean, H - 1)], fill=1))
    bars = np.zeros_like(shaft)
    for mx in (x0 + round((x1 - x0) * 0.28), x1 - round((x1 - x0) * 0.28)):
        t = (YY - FLOOR_Y) / (H - FLOOR_Y)
        bars |= np.abs(XX - (mx + lean * t)) <= 1 + 2 * t
    cv.shift(FLOOR & shaft & ~bars & (checker() | (YY < FLOOR_Y + 12)), 1)
    # The front edge of the floor falls into shadow.
    cv.shift(FLOOR & (YY >= H - 6) & checker(), -1)
    cv.shift(FLOOR & (YY >= H - 3), -1)
    # Contact shadow where the floor meets the walls.
    cv.shift(FLOOR & ((YY == BOT) | (YY == BOT + 1)), -1)


# ------------------------------------------------------------------ decor
# Wall dressing that Marycel does not use. Station furniture stands in front
# of it, so anything behind a station sits above the furniture tops.

PAPER, PLASTIC_LIGHT, PLASTIC_MID = (244, 240, 226), (190, 176, 146), (140, 126, 102)


def edge_shadow(cv: Canvas, x0, y0, x1, y1) -> None:
    """One-pixel drop shadow to the right of and below a wall item."""
    cv.shift(WALL & (XX == x1 + 1) & (YY > y0) & (YY <= y1 + 1), -1)
    cv.shift(WALL & (YY == y1 + 1) & (XX > x0) & (XX <= x1), -1)


def shelf(cv: Canvas, x0, x1, y, items, ramp) -> None:
    """A plank on two brackets with items standing on it (top surface is row y)."""
    x = x0 + 3
    for item in items:
        x = ITEMS[item](cv, x, y - 1) + 2
    cv.rect(x0, y, x1, y + 2, ramp[3])
    cv.rect(x0, y + 2, x1, y + 2, ramp[1])
    cv.shift(WALL & (XX >= x0) & (XX <= x1) & (YY == y + 3), -1)
    for bx in (x0 + 5, x1 - 6):
        cv.rect(bx, y + 3, bx + 1, y + 8, ramp[1])
        cv.rect(bx + 1, y + 3, bx + 3, y + 3, ramp[1])


def _books(cv, x, base):
    cols = [R["rose"][1], R["green"][2], R["night"][3], R["warm_wood"][4], R["metal"][2], R["red_wood"][3]]
    for _ in range(int(cv.rng.integers(4, 7))):
        h = int(cv.rng.integers(8, 12))
        cv.rect(x, base - h + 1, x + 2, base, cols[int(cv.rng.integers(len(cols)))])
        cv.shift((XX == x + 2) & (YY > base - h) & (YY <= base), -1)
        cv.px(x + 1, base - h + 4, PAPER)
        x += 3
    return x


def _jar(cv, x, base):
    cv.rect(x, base - 6, x + 4, base, R["grey_brown"][5])
    cv.rect(x + 1, base - 4, x + 3, base - 1, R["brass"][1])
    cv.rect(x, base - 7, x + 4, base - 7, R["metal"][2])
    return x + 4


def _box(cv, x, base):
    cv.rect(x, base - 8, x + 13, base, R["warm_wood"][4])
    cv.rect(x, base - 8, x + 13, base - 8, R["warm_wood"][5])
    cv.rect(x + 13, base - 8, x + 13, base, R["warm_wood"][3])
    cv.rect(x + 5, base - 8, x + 7, base - 4, PLASTIC_LIGHT)
    return x + 13


def _radio(cv, x, base):
    cv.rect(x, base - 9, x + 15, base, R["red_wood"][3])
    cv.rect(x, base - 9, x + 15, base - 9, R["red_wood"][4])
    cv.rect(x + 2, base - 7, x + 8, base - 2, R["red_wood"][1])
    for gx in range(x + 3, x + 8, 2):
        cv.rect(gx, base - 6, gx, base - 3, R["red_wood"][0])
    cv.rect(x + 10, base - 6, x + 13, base - 5, R["lamp"][1])
    cv.px(x + 11, base - 2, R["brass"][1])
    cv.px(x + 13, base - 2, R["brass"][1])
    return x + 15


def _plant(cv, x, base):
    cv.rect(x + 1, base - 4, x + 6, base, R["red_wood"][3])
    cv.rect(x, base - 4, x + 7, base - 4, R["red_wood"][4])
    for lx, ly, c in ((3, 6, 2), (1, 8, 3), (5, 9, 2), (2, 11, 3), (6, 7, 3), (4, 12, 2), (0, 6, 2)):
        cv.rect(x + lx, base - ly, x + lx + 1, base - ly + 1, R["green"][c])
    return x + 7


def _scope(cv, x, base):
    """Oscilloscope with a green trace."""
    cv.rect(x, base - 11, x + 17, base, R["metal"][2])
    cv.rect(x, base - 11, x + 17, base - 11, R["metal"][3])
    cv.rect(x + 2, base - 9, x + 10, base - 2, R["night"][0])
    for i, gx in enumerate(range(x + 3, x + 10)):
        cv.px(gx, base - 6 + (0, -2, -1, 1, 2, 0, -1)[i], (64, 196, 112))
    for ky in (base - 8, base - 5, base - 2):
        cv.px(x + 13, ky, R["metal"][0])
        cv.px(x + 15, ky, R["brass"][1])
    return x + 17


ITEMS = {"books": _books, "jar": _jar, "box": _box, "radio": _radio, "plant": _plant, "scope": _scope}


def clock(cv: Canvas, cx, cy, ramp) -> None:
    cv.put(cv.mask(lambda d: d.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=1)), ramp[1])
    cv.put(cv.mask(lambda d: d.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=1)), PAPER)
    for tx, ty in ((0, -4), (4, 0), (0, 4), (-4, 0)):
        cv.px(cx + tx, cy + ty, R["metal"][1])
    cv.rect(cx, cy - 3, cx, cy, INK)  # hands at about ten o'clock
    cv.rect(cx - 2, cy - 1, cx, cy - 1, INK)
    cv.px(cx - 5, cy - 5, ramp[3])


def framed(cv: Canvas, x0, y0, x1, y1, kind, ramp) -> None:
    """Family photo, calendar or schematic poster."""
    if kind == "photo":
        cv.rect(x0, y0, x1, y1, ramp[1])
        cv.rect(x0, y0, x1, y0, ramp[3])
        cv.rect(x0 + 2, y0 + 2, x1 - 2, y1 - 2, PLASTIC_LIGHT)
        cv.rect(x0 + 2, y1 - 5, x1 - 2, y1 - 2, R["green"][2])
        n = max(1, (x1 - x0 - 4) // 6)
        for i in range(n):  # family members, the last one a child
            fx = x0 + 4 + i * 6
            hgt = 9 - (i % 2) * 2 - (3 if i == n - 1 and n > 2 else 0)
            body = (R["rose"][1], R["night"][3], R["warm_wood"][4])[i % 3]
            cv.rect(fx, y1 - hgt + 1, fx + 3, y1 - 3, body)
            cv.rect(fx + 1, y1 - hgt - 2, fx + 2, y1 - hgt, R["red_wood"][2])
    elif kind == "calendar":
        cv.rect(x0, y0, x1, y1, PAPER)
        cv.rect(x0, y0, x1, y0 + 4, R["rose"][1])
        cv.rect((x0 + x1) // 2, y0 - 2, (x0 + x1) // 2, y0, INK)
        for gy in range(y0 + 7, y1 - 1, 3):
            for gx in range(x0 + 2, x1 - 1, 3):
                cv.px(gx, gy, PLASTIC_MID)
        cv.rect(x0 + 7, y0 + 9, x0 + 9, y0 + 11, R["rose"][1])  # a marked day
    elif kind == "schematic":
        lc = R["star"][0]
        cv.rect(x0, y0, x1, y1, R["night"][3])
        cv.rect(x0, y0, x1, y0, R["night"][4])
        cv.rect(x0 + 4, y0 + 6, x1 - 6, y0 + 6, lc)
        cv.rect(x1 - 6, y0 + 6, x1 - 6, y1 - 8, lc)
        cv.rect(x0 + 10, y1 - 8, x1 - 6, y1 - 8, lc)
        cv.rect(x0 + 10, y0 + 12, x0 + 10, y1 - 8, lc)
        cv.rect(x0 + 14, y0 + 10, x0 + 22, y0 + 14, R["night"][4])  # chip
        cv.put(cv.mask(lambda d: d.ellipse((x0 + 26, y1 - 18, x0 + 32, y1 - 12), outline=1)), lc)
        for cx_ in (x0 + 1, x1 - 1):
            cv.px(cx_, y0 + 1, R["brass"][1])
    edge_shadow(cv, x0, y0, x1, y1)


def pegboard(cv: Canvas, x0, y0, x1, y1) -> None:
    m, wood = R["metal"], R["warm_wood"]
    cv.rect(x0, y0, x1, y1, PLASTIC_LIGHT)
    cv.rect(x0, y0, x1, y0, PAPER)
    cv.rect(x0, y1, x1, y1, PLASTIC_MID)
    for hy in range(y0 + 3, y1 - 1, 4):
        for hx in range(x0 + 3, x1 - 1, 4):
            cv.px(hx, hy, PLASTIC_MID)
    x = x0 + 6
    cv.rect(x + 2, y0 + 8, x + 3, y0 + 26, wood[3])  # hammer
    cv.rect(x - 1, y0 + 5, x + 6, y0 + 8, m[2])
    x += 14
    cv.rect(x + 1, y0 + 9, x + 2, y0 + 27, m[3])  # wrench
    cv.rect(x - 1, y0 + 5, x + 4, y0 + 8, m[3])
    cv.rect(x + 1, y0 + 5, x + 2, y0 + 6, PLASTIC_LIGHT)
    x += 12
    for c in (R["rose"][1], R["lamp"][1], R["night"][3]):  # screwdrivers
        cv.rect(x, y0 + 5, x + 2, y0 + 11, c)
        cv.rect(x + 1, y0 + 12, x + 1, y0 + 21, m[3])
        x += 6
    x += 4
    cv.rect(x, y0 + 6, x + 1, y0 + 12, m[2])  # pliers
    cv.rect(x + 3, y0 + 6, x + 4, y0 + 12, m[2])
    cv.rect(x - 1, y0 + 13, x, y0 + 24, R["rose"][1])
    cv.rect(x + 4, y0 + 13, x + 5, y0 + 24, R["rose"][1])
    x += 12
    if x + 12 < x1:  # coil of solder wire
        cv.put(cv.mask(lambda d: d.ellipse((x, y0 + 6, x + 11, y0 + 17), outline=1, width=2)), R["brass"][1])
    edge_shadow(cv, x0, y0, x1, y1)


def parts_cabinet(cv: Canvas, x0, y0, cols, rows) -> None:
    m = R["metal"]
    x1, y1 = x0 + cols * 9 + 2, y0 + rows * 6 + 2
    cv.rect(x0, y0, x1, y1, m[1])
    cv.rect(x0, y0, x1, y0, m[3])
    for r in range(rows):
        for c in range(cols):
            dx, dy = x0 + 2 + c * 9, y0 + 2 + r * 6
            cv.rect(dx, dy, dx + 7, dy + 4, m[2])
            cv.rect(dx + 2, dy + 1, dx + 5, dy + 2, PAPER if (r + c) % 3 else R["lamp"][1])
            cv.px(dx + 3, dy + 3, m[0])
    edge_shadow(cv, x0, y0, x1, y1)


def cable_coil(cv: Canvas, cx, cy) -> None:
    cv.rect(cx - 1, cy - 2, cx + 1, cy, R["brass"][1])  # hook
    cv.put(cv.mask(lambda d: d.ellipse((cx - 8, cy, cx + 8, cy + 18), outline=1, width=2)), R["night"][0])
    cv.put(cv.mask(lambda d: d.ellipse((cx - 6, cy + 2, cx + 6, cy + 16), outline=1)), R["metal"][1])
    cv.rect(cx + 5, cy + 16, cx + 6, cy + 30, R["night"][0])  # loose end


def hanging_lamp(cv: Canvas, x, y, shade) -> None:
    """Pendant lamp; y is the bottom of the shade. Lights the wall around it."""
    glow = (XX - x) ** 2 + ((YY - y - 6) * 1.6) ** 2
    cv.shift(WALL & (glow < 26 ** 2) & checker(), 1)
    cv.shift(WALL & (glow < 16 ** 2) & ~checker(), 1)
    cv.rect(x, 0, x, y - 6, INK)
    cv.poly([(x - 2, y - 6), (x + 2, y - 6), (x + 7, y), (x - 7, y)], shade[2])
    cv.rect(x - 7, y, x + 7, y, shade[1])
    cv.rect(x - 1, y - 6, x - 1, y - 5, shade[-1])
    cv.rect(x - 2, y + 1, x + 2, y + 2, R["lamp"][2])
    cv.rect(x - 1, y + 3, x + 1, y + 3, R["lamp"][1])


def rug(cv: Canvas, x0, x1, y0, y1) -> None:
    outer = [(x0 + 10, y0), (x1 - 10, y0), (x1, y1), (x0, y1)]
    inner = [(x0 + 14, y0 + 2), (x1 - 14, y0 + 2), (x1 - 5, y1 - 2), (x0 + 5, y1 - 2)]
    cv.poly(outer, R["rose"][1])
    cv.poly(inner, R["rose"][0])
    cv.put(cv.mask(lambda d: d.polygon(inner, fill=1)) & ((XX // 3 + YY) % 6 == 0), R["mauve"][3])
    cv.line([(x0, y1 + 1), (x1, y1 + 1)], R["red_wood"][0])


def decorate(cv: Canvas, name: str) -> None:
    b = PILLARS
    if name == "repair-shop":
        w = R["warm_wood"]
        shelf(cv, b[0] + 22, b[0] + 120, 78, ["radio", "box", "jar", "jar", "radio"], w)
        clock(cv, b[0] + 160, 58, w)
        pegboard(cv, b[1] + 20, 56, b[1] + 118, 100)
        framed(cv, b[3] + 24, 54, b[3] + 44, 78, "calendar", w)
        shelf(cv, b[3] + 64, b[3] + 176, 84, ["box", "books", "radio", "box"], w)
    elif name == "electronics-workshop":
        g = R["grey_brown"]
        framed(cv, b[0] + 16, 54, b[0] + 66, 96, "schematic", g)
        parts_cabinet(cv, b[0] + 108, 60, 8, 5)
        shelf(cv, b[1] + 24, b[1] + 150, 80, ["scope", "radio", "jar", "box", "scope"], R["metal"])
        pegboard(cv, b[3] + 14, 54, b[3] + 112, 100)
        cable_coil(cv, b[3] + 150, 58)
        framed(cv, b[3] + 166, 56, b[3] + 186, 80, "calendar", g)
    else:
        rw = R["red_wood"]
        pegboard(cv, b[0] + 30, 56, b[0] + 128, 100)
        framed(cv, b[1] + 22, 52, b[1] + 50, 74, "photo", rw)
        framed(cv, b[1] + 60, 46, b[1] + 100, 80, "photo", rw)
        framed(cv, b[1] + 110, 54, b[1] + 132, 72, "photo", rw)
        clock(cv, b[1] + 168, 62, rw)
        shelf(cv, b[3] + 26, b[3] + 150, 84, ["plant", "books", "radio", "books", "plant"], rw)
        framed(cv, b[3] + 160, 58, b[3] + 180, 82, "calendar", rw)


def lamps_and_rug(cv: Canvas, name: str) -> None:
    shade = {"repair-shop": R["green"], "electronics-workshop": R["metal"], "home-workshop": R["brass"]}[name]
    for i in (0, 1, 3):
        x = PILLARS[i] + BAY // 2
        hanging_lamp(cv, x, 40, shade)
        pool = ((XX - x) / 46.0) ** 2 + ((YY - FLOOR_Y - 9) / 7.0) ** 2
        cv.shift(FLOOR & (pool < 1) & (checker() | (pool < 0.4)), 1)
    if name == "home-workshop":
        rug(cv, PILLARS[1] + 60, PILLARS[2] + 30, 188, 210)


# ------------------------------------------------------------------ texture


def knots(cv: Canvas, ramp, n=18) -> None:
    for _ in range(n):
        x, y = int(cv.rng.integers(4, W - 4)), int(cv.rng.integers(CEIL_Y + 6, FLOOR_Y - 10))
        if not WALL[y, x]:
            continue
        cv.put(WALL & (np.abs(XX - x) <= 1) & (np.abs(YY - y) <= 2) & ~((np.abs(XX - x) == 1) & (np.abs(YY - y) == 2)), ramp[1])
        cv.px(x, y, ramp[0])
        cv.px(x - 1, y - 3, ramp[3])


def cracks(cv: Canvas, colour, n=10) -> None:
    for _ in range(n):
        x, y = int(cv.rng.integers(LEFT_X + 10, RIGHT_X - 10)), int(cv.rng.integers(CEIL_Y + 4, FLOOR_Y - 30))
        for _ in range(int(cv.rng.integers(8, 26))):
            if WALL[y, x]:
                cv.px(x, y, colour)
            y += 1
            x += int(cv.rng.choice([-1, 0, 0, 1]))
            if cv.rng.random() < 0.12:  # short branch
                cv.px(x + 1, y, colour)


def cobwebs(cv: Canvas, colour) -> None:
    for cx, sx in ((LEFT_X - 5, 1), (RIGHT_X + 5, -1)):
        cy = CEIL_Y
        for ang in (0.15, 0.6, 1.05, 1.45):
            ex, ey = cx + sx * round(14 * math.cos(ang)), cy + round(14 * math.sin(ang))
            cv.line([(cx, cy), (ex, ey)], colour)
        for r in (6, 11):
            pts = [(cx + sx * round(r * math.cos(a)), cy + round(r * math.sin(a))) for a in np.linspace(0.15, 1.45, 5)]
            cv.line(pts, colour)


# ------------------------------------------------------------------ clutter


def cbox(cv: Canvas, x0, y0, x1, y1, ramp, mid=2) -> None:
    """Outlined block lit from the top-left (same look as the props)."""
    cv.rect(x0, y0, x1, y1, INK)
    cv.rect(x0 + 1, y0 + 1, x1 - 1, y1 - 1, ramp[mid])
    cv.rect(x0 + 1, y0 + 1, x1 - 1, y0 + 1, ramp[min(mid + 1, len(ramp) - 1)])
    cv.rect(x0 + 1, y0 + 1, x0 + 1, y1 - 1, ramp[min(mid + 1, len(ramp) - 1)])
    cv.rect(x0 + 1, y1 - 1, x1 - 1, y1 - 1, ramp[mid - 1])
    cv.rect(x1 - 1, y0 + 2, x1 - 1, y1 - 1, ramp[mid - 1])


CLUTTER_BASE = FLOOR_Y + 12  # back-floor items stand on this row, behind the stations


def old_tv(cv: Canvas, x, base, antenna=False, tag=False) -> int:
    """Wooden-cabinet television waiting for repair; returns its top row."""
    top = base - 24
    cbox(cv, x, top, x + 31, base, R["red_wood"], mid=3)
    cv.rect(x + 3, top + 3, x + 21, top + 19, INK)
    cv.rect(x + 4, top + 4, x + 20, top + 18, R["night"][1])
    cv.rect(x + 5, top + 5, x + 8, top + 6, R["night"][3])  # glare
    for ky in (top + 5, top + 10):
        cv.rect(x + 24, ky, x + 27, ky + 2, R["brass"][1])
    for gy in range(top + 15, top + 20, 2):
        cv.rect(x + 23, gy, x + 28, gy, R["red_wood"][1])
    if antenna:
        cv.line([(x + 15, top), (x + 7, top - 12)], R["metal"][3])
        cv.line([(x + 16, top), (x + 25, top - 11)], R["metal"][3])
        cv.rect(x + 13, top - 2, x + 18, top - 1, R["metal"][1])
    if tag:
        cv.line([(x + 29, top + 6), (x + 33, top + 12)], INK)
        cv.rect(x + 31, top + 12, x + 36, top + 18, (244, 240, 226))
        cv.rect(x + 32, top + 14, x + 35, top + 14, R["rose"][1])
    return top


def crt_monitor(cv: Canvas, x, base) -> int:
    top = base - 18
    cbox(cv, x, top, x + 23, base, [(92, 80, 66), (140, 126, 102), (190, 176, 146), (226, 214, 184)], mid=2)
    cv.rect(x + 3, top + 3, x + 17, top + 13, INK)
    cv.rect(x + 4, top + 4, x + 16, top + 12, (24, 32, 28))
    cv.px(x + 20, top + 14, (140, 126, 102))
    return top


def crate(cv: Canvas, x, base, w=34, h=22, ramp=None) -> int:
    ramp = ramp or R["warm_wood"]
    top = base - h
    cbox(cv, x, top, x + w, base, ramp, mid=3)
    for sy in range(top + 6, base - 2, 6):
        cv.rect(x + 1, sy, x + w - 1, sy, ramp[1])
    cv.line([(x + 2, base - 2), (x + w - 2, top + 2)], ramp[2])
    cv.rect(x + w // 2 - 4, top + 8, x + w // 2 + 4, top + 11, R["ink"][0])  # stencil
    return top


def moving_box(cv: Canvas, x, base, w=30, h=20) -> int:
    top = base - h
    cbox(cv, x, top, x + w, base, R["warm_wood"], mid=4)
    cv.rect(x + w // 2 - 2, top + 1, x + w // 2 + 1, top + 5, (190, 176, 146))  # tape
    cv.line([(x + 1, top + 4), (x + w - 1, top + 4)], R["warm_wood"][3])
    cv.line([(x + 5, top + 10), (x + 14, top + 10)], INK)  # marker writing
    cv.line([(x + 5, top + 12), (x + 11, top + 12)], INK)
    return top


def coat_rack(cv: Canvas, x, base) -> None:
    rw = R["red_wood"]
    cv.rect(x - 1, base - 74, x + 1, base, rw[2])
    cv.rect(x - 1, base - 74, x - 1, base, rw[3])
    cv.rect(x - 7, base - 1, x + 7, base, rw[1])
    for hx in (x - 5, x + 5):
        cv.line([(x, base - 70), (hx, base - 74)], rw[3])
    # long coat on the left hook, scarf on the right, hat on top
    cv.poly([(x - 5, base - 72), (x - 1, base - 70), (x - 2, base - 30), (x - 12, base - 30), (x - 10, base - 64)], R["night"][2])
    cv.line([(x - 6, base - 66), (x - 8, base - 34)], R["night"][1])
    cv.rect(x + 3, base - 72, x + 5, base - 46, R["rose"][1])
    for fy in range(base - 50, base - 45, 2):
        cv.px(x + 4, fy, R["rose"][2])
    cv.rect(x - 6, base - 79, x + 6, base - 77, rw[1])
    cv.rect(x - 4, base - 83, x + 4, base - 78, rw[1])
    cv.rect(x - 4, base - 79, x + 4, base - 79, R["rose"][0])


def switch_plate(cv: Canvas, x, y) -> None:
    cv.rect(x, y, x + 4, y + 7, (226, 214, 184))
    cv.rect(x + 4, y + 1, x + 4, y + 7, (140, 126, 102))
    cv.rect(x + 2, y + 2, x + 2, y + 4, (92, 80, 66))


def outlet(cv: Canvas, x) -> None:
    y = FLOOR_Y - 13
    cv.rect(x, y, x + 4, y + 5, (226, 214, 184))
    cv.rect(x + 4, y + 1, x + 4, y + 5, (140, 126, 102))
    cv.px(x + 1, y + 2, INK)
    cv.px(x + 3, y + 2, INK)


def wall_cable(cv: Canvas, x0, x1) -> None:
    """Cable taped along the baseboard."""
    y = FLOOR_Y - 9
    cv.rect(x0, y, x1, y, R["night"][0])
    for tx in range(x0 + 10, x1, 30):
        cv.rect(tx, y - 1, tx + 1, y + 1, (190, 176, 146))


def clutter(cv: Canvas, name: str) -> None:
    """Background floor clutter and fixtures; drawn after the floor."""
    b = PILLARS
    base = CLUTTER_BASE
    for i in range(4):
        outlet(cv, b[i] + 30)
    switch_plate(cv, RIGHT_X - 16, 98)
    if name == "repair-shop":
        top = old_tv(cv, 214, base, tag=True)
        old_tv(cv, 216, top, antenna=True)
        old_tv(cv, 412, base, tag=True)
        crate(cv, 790, base, w=30, h=18)
        moving_box(cv, 826, base, w=26, h=14)
        cobwebs(cv, R["warm_wood"][5])
    elif name == "electronics-workshop":
        top = crt_monitor(cv, 300, base)
        top = crt_monitor(cv, 302, top)
        crt_monitor(cv, 330, base)
        top = crate(cv, 360, base, ramp=R["grey_brown"])
        crate(cv, 364, top, w=26, h=14, ramp=R["grey_brown"])
        crate(cv, 820, base, w=30, h=20, ramp=R["grey_brown"])
        wall_cable(cv, b[1] + 30, 440)
        cobwebs(cv, R["grey_brown"][5])
    else:
        top = moving_box(cv, 300, base, w=32, h=20)
        moving_box(cv, 304, top, w=26, h=16)
        moving_box(cv, 338, base, w=24, h=14)
        moving_box(cv, 640, base, w=28, h=18)
        coat_rack(cv, 858, base)
        cobwebs(cv, R["mauve"][3])


# ------------------------------------------------------------------ rooms


def draw(name: str, colours: np.ndarray) -> Image.Image:
    cfg = ROOMS[name]
    cv = Canvas(colours, cfg["seed"])
    wall_ramp, trim = R[cfg["wall_ramp"]], R[cfg["trim"]]
    {"wood": wood_wall, "plaster": plaster_wall, "wallpaper": wallpaper_wall}[cfg["wall"]](cv, WALL, wall_ramp)
    if cfg["pillar"] == "metal":
        baseboard(cv, R["metal"], base=1)
    else:
        baseboard(cv, trim, base=1)
    cv.shift(SIDES, -1)  # side walls face away from the light
    cv.shift(BACK & (YY < CEIL_Y + 2), -1)  # shadow under the ceiling beam
    cv.shift(BACK & (YY == CEIL_Y + 2) & checker(), -1)
    if cfg["wall"] == "wood":
        knots(cv, wall_ramp)
    elif cfg["wall"] == "plaster":
        cracks(cv, wall_ramp[0], n=14)
    else:
        cracks(cv, wall_ramp[0], n=5)
    if name == "electronics-workshop":
        conduit(cv)
    for x in PILLARS:
        (metal_pillar if cfg["pillar"] == "metal" else wood_pillar)(cv, x, trim)
    window(cv, trim)
    door(cv, trim)
    decorate(cv, name)
    ceiling(cv, R[cfg["ceiling"]])
    floor(cv, R[cfg["floor"]], base=2)
    lamps_and_rug(cv, name)
    clutter(cv, name)
    return Image.fromarray(cv.a, "RGB")


def shade(img: Image.Image, colours: np.ndarray, mask: np.ndarray, d: int) -> Image.Image:
    """Shift masked pixels of a finished room one ramp step (e.g. furniture shadows)."""
    cv = Canvas(colours, 0)
    cv.a = np.array(img.convert("RGB"))
    cv.shift(mask, d)
    return Image.fromarray(cv.a, "RGB")


def main() -> None:
    out = ps.PIXEL_OUT / "rooms"
    out.mkdir(parents=True, exist_ok=True)
    colours = ps.load_palette()
    for name in ROOMS:
        draw(name, colours).save(out / f"{name}.png")


if __name__ == "__main__":
    main()
