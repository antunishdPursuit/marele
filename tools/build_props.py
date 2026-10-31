"""Draw the props: furniture, devices and story objects, at native size.

Every prop uses the room ramps from pixel_spec.ROOM_RAMPS with a dark outline,
a lit top-left edge and a shaded bottom-right edge, so props match the rooms.
Interactive props also get an `_outline` sprite: a 1px bright ring the game
shows when the player points at the object (hover highlight).
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

import pixel_spec as ps

R = ps.ROOM_RAMPS
WOOD = R["warm_wood"]
BEIGE = [(92, 80, 66), (140, 126, 102), (190, 176, 146), (226, 214, 184)]
METAL, NIGHT, LAMP, BRASS, ROSE, GREEN = R["metal"], R["night"], R["lamp"], R["brass"], R["rose"], R["green"]
OUTLINE = (24, 16, 14)
INK = R["ink"][0]
PAPER = (244, 240, 226)
PHOSPHOR, PHOSPHOR_DIM, SCREEN_OFF = (64, 196, 112), (34, 110, 66), (24, 32, 28)
HIGHLIGHT = R["star"][0]  # hover outline colour


class Pen:
    """Draws with palette colours only: every requested colour is snapped."""

    def __init__(self, size, colours):
        self.img = Image.new("RGBA", size, (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.colours = colours

    def c(self, rgb):
        return ps.nearest(self.colours, rgb) + (255,)

    def rect(self, x0, y0, x1, y1, fill, outline=None):
        self.d.rectangle((x0, y0, x1, y1), fill=self.c(fill), outline=self.c(outline) if outline else None)

    def line(self, pts, rgb):
        self.d.line(pts, fill=self.c(rgb))

    def px(self, x, y, rgb):
        self.d.point((x, y), fill=self.c(rgb))

    def poly(self, pts, rgb):
        self.d.polygon(pts, fill=self.c(rgb))

    def ellipse(self, box, fill=None, outline=None):
        self.d.ellipse(box, fill=self.c(fill) if fill else None, outline=self.c(outline) if outline else None)

    def clear(self, x, y):
        self.d.point((x, y), fill=(0, 0, 0, 0))

    def box(self, x0, y0, x1, y1, ramp, mid=2):
        """Outlined block lit from the top-left."""
        self.rect(x0, y0, x1, y1, ramp[mid], OUTLINE)
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            self.line([(x0 + 1, y0 + 1), (x1 - 1, y0 + 1)], ramp[min(mid + 1, len(ramp) - 1)])
            self.line([(x0 + 1, y0 + 1), (x0 + 1, y1 - 1)], ramp[min(mid + 1, len(ramp) - 1)])
            self.line([(x0 + 1, y1 - 1), (x1 - 1, y1 - 1)], ramp[mid - 1])
            self.line([(x1 - 1, y0 + 2), (x1 - 1, y1 - 1)], ramp[mid - 1])


def outline_of(img: Image.Image) -> Image.Image:
    """1px ring around the opaque pixels, for the hover highlight."""
    a = np.asarray(img)[..., 3] > 0
    pad = np.pad(a, 1)
    grown = np.zeros_like(pad)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if abs(dx) + abs(dy) == 1:
                grown |= np.roll(np.roll(pad, dy, 0), dx, 1)
    ring = grown & ~pad
    out = np.zeros(ring.shape + (4,), np.uint8)
    out[ring] = HIGHLIGHT + (255,)
    return Image.fromarray(out)


# ------------------------------------------------------------------ furniture


def desk(colours, w=64, h=48):
    p = Pen((w, h), colours)
    p.rect(8, 6, 10, h - 2, WOOD[1], OUTLINE)  # back leg, in shadow
    p.box(2, 5, 6, h - 1, WOOD)  # front leg
    dx = w - 26
    p.box(dx, 5, w - 3, h - 1, WOOD, mid=2)  # drawer unit
    for i, y in enumerate(range(8, h - 6, 11)):
        p.box(dx + 2, y, w - 5, y + 9, WOOD, mid=3)
        p.rect(dx + 9, y + 4, dx + 14, y + 5, BRASS[1])
        p.px(dx + 9, y + 4, BRASS[2])
    p.line([(7, 6), (dx - 1, 6)], WOOD[0])  # shadow under the top
    p.box(0, 0, w - 1, 5, WOOD, mid=3)  # top slab
    p.line([(1, 1), (w - 2, 1)], WOOD[5])
    for gx in (12, 31, 47):  # grain on the front edge
        p.line([(gx, 3), (gx + 4, 3)], WOOD[2])
    return p.img


def printer_table(colours, w=50, h=38):
    p = Pen((w, h), colours)
    p.rect(7, 6, 9, h - 2, WOOD[1], OUTLINE)
    p.rect(w - 10, 6, w - 8, h - 2, WOOD[1], OUTLINE)
    p.box(2, 5, 6, h - 1, WOOD)
    p.box(w - 7, 5, w - 3, h - 1, WOOD)
    p.box(5, h - 12, w - 6, h - 9, WOOD, mid=2)  # lower shelf
    p.box(0, 0, w - 1, 5, WOOD, mid=3)
    p.line([(1, 1), (w - 2, 1)], WOOD[5])
    p.line([(10, 3), (14, 3)], WOOD[2])
    return p.img


def chair(colours):
    """Office chair, side view, seat towards the desk (left). Sized to Marycel's seated
    pose: the seat top is 29 px above the floor, under her hips, and the backrest rises
    behind her back so it shows while she sits."""
    w, h = 34, 64
    p = Pen((w, h), colours)
    seat = h - 29  # seat top row
    p.rect(15, seat + 5, 17, h - 6, METAL[2], OUTLINE)  # gas column
    p.line([(2, h - 5), (31, h - 5)], METAL[1])  # base
    p.line([(3, h - 4), (30, h - 4)], OUTLINE)
    for x in (3, 16, 30):
        p.rect(x - 1, h - 3, x + 1, h - 2, INK)  # castors
    p.box(0, seat, 30, seat + 4, GREEN, mid=1)  # seat
    p.rect(28, 14, 30, seat + 1, METAL[1], OUTLINE)  # back post
    p.box(26, 2, 33, 26, GREEN, mid=1)  # backrest
    return p.img


def workbench(colours):
    """Bench with a vise, a radio opened for repair, iron, magnifier lamp, toolbox."""
    w, legs = 84, 44
    h = legs + 24
    p = Pen((w, h), colours)
    top = h - legs
    p.rect(9, top + 6, 11, h - 2, WOOD[0], OUTLINE)
    p.rect(w - 13, top + 6, w - 11, h - 2, WOOD[0], OUTLINE)
    p.box(3, top + 5, 8, h - 1, WOOD, mid=2)
    p.box(w - 9, top + 5, w - 4, h - 1, WOOD, mid=2)
    p.box(4, h - 13, w - 5, h - 10, WOOD, mid=2)  # lower shelf
    p.box(14, h - 22, 33, h - 14, ROSE, mid=1)  # toolbox
    p.rect(21, h - 24, 26, h - 23, METAL[2], OUTLINE)
    p.rect(22, h - 19, 25, h - 18, BRASS[1])
    p.box(0, top, w - 1, top + 6, WOOD, mid=2)  # thick top
    p.line([(1, top + 1), (w - 2, top + 1)], WOOD[4])
    for gx, gy in ((8, 3), (30, 4), (52, 3), (66, 4)):
        p.line([(gx, top + gy), (gx + 7, top + gy)], WOOD[1])
    p.box(2, top - 7, 13, top - 1, METAL, mid=2)  # vise
    p.box(5, top - 10, 10, top - 7, METAL, mid=2)
    p.line([(0, top - 4), (2, top - 4)], METAL[3])
    p.px(0, top - 5, METAL[3])
    p.rect(24, top - 3, 31, top - 1, METAL[1], OUTLINE)  # iron stand
    for sx in range(25, 31, 2):
        p.px(sx, top - 4, METAL[3])
    p.line([(27, top - 10), (33, top - 4)], METAL[3])
    p.line([(26, top - 11), (27, top - 10)], ROSE[1])
    p.box(46, top - 12, 69, top - 1, R["red_wood"], mid=3)  # radio, back off
    p.rect(48, top - 10, 58, top - 3, GREEN[1])  # circuit board
    for cx, cy, c in ((49, 9, BRASS[1]), (52, 7, ROSE[1]), (55, 9, PAPER), (51, 5, BRASS[2]), (57, 6, NIGHT[3])):
        p.px(cx, top - cy, c)
    p.line([(48, top - 5), (57, top - 5)], GREEN[3])
    p.rect(61, top - 9, 67, top - 6, LAMP[1])  # dial
    p.px(64, top - 9, OUTLINE)
    p.rect(77, top - 22, 78, top - 1, METAL[2], OUTLINE)  # magnifier lamp
    p.line([(77, top - 22), (66, top - 22)], METAL[2])
    p.ellipse((60, top - 23, 68, top - 19), fill=METAL[1], outline=OUTLINE)
    p.line([(62, top - 18), (66, top - 18)], LAMP[2])
    p.box(36, top - 6, 41, top - 1, ROSE, mid=1)  # mug
    p.px(42, top - 4, ROSE[1])
    p.line([(37, top - 5), (40, top - 5)], R["red_wood"][0])
    return p.img


def ofrenda(colours, lit=True):
    """Small family ofrenda: papel picado, cloth-covered riser, marigolds,
    candles, pan de muerto and a sugar skull. The family photo is a separate
    item placed on the riser."""
    w, h = 48, 62
    p = Pen((w, h), colours)
    # Papel picado on a string.
    p.line([(0, 1), (w - 1, 1)], INK)
    flag_cols = [ROSE[1], LAMP[1], GREEN[3], NIGHT[4], ROSE[2]]
    for i, fx in enumerate(range(1, w - 7, 9)):
        c = flag_cols[i % len(flag_cols)]
        p.rect(fx, 2, fx + 7, 9, c)
        for x in range(fx, fx + 8, 2):  # zigzag edge
            p.clear(x, 9)
        for hx, hy in ((fx + 2, 4), (fx + 5, 4), (fx + 3, 6), (fx + 4, 6)):  # cut pattern
            p.clear(hx, hy)
    top = h - 26  # table top row
    p.rect(5, top + 5, 8, h - 1, R["red_wood"][2], OUTLINE)  # legs
    p.rect(w - 9, top + 5, w - 6, h - 1, R["red_wood"][2], OUTLINE)
    p.rect(1, top, w - 2, top + 8, PAPER, OUTLINE)  # cloth
    for x in range(2, w - 2, 2):
        p.px(x, top + 8, BEIGE[2])
        p.clear(x + 1, top + 9)
    p.line([(2, top + 1), (w - 3, top + 1)], BEIGE[3])
    p.rect(12, top - 9, w - 13, top - 1, PAPER, OUTLINE)  # riser
    p.line([(13, top - 2), (w - 14, top - 2)], BEIGE[2])
    for x in (3, w - 6):  # candles
        p.rect(x, top - 7, x + 2, top - 1, PAPER, OUTLINE)
        if lit:
            p.px(x + 1, top - 9, LAMP[2])
            p.px(x + 1, top - 8, LAMP[1])
        else:
            p.px(x + 1, top - 8, INK)  # wick
    for vx in (7, w - 12):  # marigolds in vases
        p.rect(vx, top - 5, vx + 3, top - 1, ROSE[0], OUTLINE)
        for mx, my in ((0, 9), (3, 8), (1, 12), (4, 11), (2, 14), (-1, 12), (5, 13)):
            p.rect(vx + mx, top - my, vx + mx + 1, top - my + 1, LAMP[1])
            p.px(vx + mx, top - my, BRASS[2])
        p.line([(vx + 1, top - 6), (vx + 2, top - 9)], GREEN[2])
    p.ellipse((16, top - 4, 21, top), fill=WOOD[4], outline=OUTLINE)  # pan de muerto
    p.px(18, top - 3, WOOD[5])
    p.rect(w - 21, top - 5, w - 17, top - 1, PAPER, OUTLINE)  # sugar skull
    p.px(w - 20, top - 3, ROSE[1])
    p.px(w - 18, top - 3, NIGHT[4])
    for x, y in ((3, h - 2), (13, h - 1), (34, h - 2), (42, h - 1), (24, h - 1)):  # petals
        p.px(x, y, LAMP[1])
    return p.img


# ------------------------------------------------------------------ devices


def crt(colours, state):
    p = Pen((34, 31), colours)
    p.rect(10, 27, 21, 30, BEIGE[1], OUTLINE)  # stand
    p.poly([(27, 1), (33, 4), (33, 24), (27, 26)], BEIGE[1])  # case depth
    p.line([(27, 1), (33, 4), (33, 24), (27, 26)], OUTLINE)
    for vy in range(7, 22, 3):
        p.line([(29, vy), (31, vy + 1)], BEIGE[0])
    p.box(0, 0, 28, 27, BEIGE, mid=2)
    p.rect(3, 3, 24, 21, BEIGE[1])  # bezel recess
    p.rect(4, 4, 23, 20, OUTLINE)
    p.rect(5, 5, 22, 19, SCREEN_OFF)
    for cx, cy in ((5, 5), (22, 5), (5, 19), (22, 19)):  # rounded glass
        p.px(cx, cy, OUTLINE)
    if state == "off":
        p.line([(7, 7), (10, 7)], PHOSPHOR_DIM)
        p.px(7, 8, PHOSPHOR_DIM)
    elif state == "on":
        for i, y in enumerate(range(7, 18, 2)):
            p.line([(7, y), (7 + (13, 8, 15, 5, 11, 9)[i], y)], PHOSPHOR_DIM)
        p.rect(7, 17, 8, 18, PHOSPHOR)
    elif state == "message":
        p.rect(7, 9, 20, 14, PHOSPHOR_DIM)
        p.rect(8, 10, 19, 13, PHOSPHOR)
        p.rect(18, 15, 19, 17, PHOSPHOR)
    p.rect(5, 23, 10, 24, BEIGE[1])  # badge
    p.rect(21, 23, 22, 24, PHOSPHOR if state != "off" else BEIGE[0])  # power LED
    p.rect(24, 22, 26, 25, BEIGE[3], OUTLINE)  # power button
    p.rect(20, 0, 26, 5, BRASS[2])  # sticky note
    p.line([(21, 2), (24, 2)], BRASS[0])
    p.line([(21, 4), (23, 4)], BRASS[0])
    return p.img


def keyboard(colours):
    p = Pen((26, 5), colours)
    p.rect(0, 1, 25, 4, BEIGE[1], OUTLINE)
    p.line([(1, 2), (24, 2)], BEIGE[2])
    for x in range(2, 24, 2):
        p.px(x, 2, BEIGE[3])
    for x in range(3, 23, 2):
        p.px(x, 3, BEIGE[3])
    p.line([(8, 3), (16, 3)], BEIGE[3])  # space bar
    return p.img


def speaker(colours, on):
    p = Pen((10, 13), colours)
    p.box(0, 0, 9, 12, BEIGE, mid=1)
    p.ellipse((1, 4, 8, 11), fill=BEIGE[0], outline=OUTLINE)
    p.rect(4, 7, 5, 8, METAL[2])
    p.rect(3, 2, 6, 2, BEIGE[0])  # tweeter
    p.px(8, 2, PHOSPHOR if on else BEIGE[0])
    return p.img


def printer(colours, power, paper):
    """Dot-matrix printer; fan-fold paper rises behind it when loaded."""
    p = Pen((36, 26), colours)
    if paper:
        p.rect(8, 0, 26, 10, PAPER, BEIGE[1])
        for y in range(1, 10, 2):  # tractor-feed holes
            p.px(9, y, BEIGE[1])
            p.px(25, y, BEIGE[1])
        p.line([(10, 5), (24, 5)], BEIGE[2])  # perforation
    p.box(0, 8, 33, 25, BEIGE, mid=2)
    p.rect(2, 9, 31, 12, BEIGE[1])  # lid
    p.line([(2, 9), (31, 9)], BEIGE[3])
    p.rect(4, 16, 27, 18, OUTLINE)  # output slot
    p.ellipse((32, 12, 35, 17), fill=METAL[2], outline=OUTLINE)  # platen knob
    p.rect(22, 20, 31, 23, BEIGE[1])  # panel
    p.px(24, 21, PHOSPHOR if power else BEIGE[0])
    p.px(27, 21, LAMP[1] if power and not paper else BEIGE[0])
    p.px(30, 21, BEIGE[3])
    return p.img


def printout(colours):
    """Page feeding out of the printer slot (drawn over the printer)."""
    p = Pen((22, 7), colours)
    p.rect(0, 0, 21, 6, PAPER, BEIGE[1])
    for y, n in ((2, 15), (4, 10)):
        for x in range(2, 2 + n, 2):
            p.px(x, y, INK)
    return p.img


def printer_cable(colours, length=48):
    """Cable from the printer's side down to the floor, plugged in."""
    p = Pen((8, length), colours)
    pts = [(0, 1), (3, 3), (4, 10), (3, 20), (5, 30), (4, length - 6), (5, length - 3)]
    p.line(pts, NIGHT[0])
    p.rect(3, length - 4, 7, length - 1, METAL[2], OUTLINE)
    p.rect(0, 0, 1, 3, METAL[1])
    return p.img


# ------------------------------------------------------------------ items


def tape(colours):
    """The family recording: a VHS cassette."""
    p = Pen((16, 7), colours)
    p.rect(0, 0, 15, 6, (30, 28, 30), OUTLINE)
    p.rect(3, 1, 12, 3, PAPER)
    p.line([(4, 2), (9, 2)], ROSE[1])
    p.px(5, 5, METAL[2])
    p.px(10, 5, METAL[2])
    return p.img


def photo(colours):
    p = Pen((9, 11), colours)
    p.rect(0, 0, 8, 10, R["red_wood"][3], OUTLINE)
    p.rect(2, 2, 6, 8, BEIGE[3])
    p.rect(2, 7, 6, 8, GREEN[2])
    p.rect(3, 4, 3, 7, ROSE[1])
    p.px(3, 3, R["red_wood"][2])
    p.rect(5, 5, 5, 7, NIGHT[3])
    p.px(5, 4, R["red_wood"][2])
    p.px(7, 10, R["red_wood"][1])  # easel foot
    return p.img


def notebook(colours):
    p = Pen((12, 4), colours)
    p.rect(0, 1, 11, 3, ROSE[1], OUTLINE)
    p.line([(1, 2), (10, 2)], ROSE[2])
    for x in range(1, 11, 2):
        p.px(x, 1, METAL[3])  # spiral
    p.line([(3, 0), (10, 0)], INK)  # pen
    p.px(9, 0, BRASS[1])
    return p.img


def paper_ream(colours):
    p = Pen((12, 5), colours)
    p.rect(0, 0, 11, 4, PAPER, BEIGE[1])
    p.line([(0, 2), (11, 2)], NIGHT[3])
    p.line([(1, 1), (10, 1)], BEIGE[3])
    return p.img


def cable_coil(colours):
    p = Pen((12, 7), colours)
    p.ellipse((0, 0, 9, 6), outline=NIGHT[0])
    p.ellipse((2, 1, 8, 5), outline=METAL[1])
    p.rect(8, 4, 11, 6, METAL[2], OUTLINE)  # plug
    return p.img


def headphones(colours):
    p = Pen((12, 9), colours)
    p.d.arc((1, 0, 10, 10), 180, 360, fill=p.c(METAL[1]), width=2)
    p.box(0, 4, 3, 8, NIGHT, mid=1)
    p.box(8, 4, 11, 8, NIGHT, mid=1)
    return p.img


def storage(colours, open_):
    """Cardboard storage box, closed or with its flaps open."""
    p = Pen((26, 20), colours)
    p.box(0, 4, 25, 19, WOOD, mid=4)
    p.line([(1, 9), (24, 9)], WOOD[3])
    p.rect(9, 11, 16, 14, PAPER)  # label
    p.line([(10, 12), (14, 12)], INK)
    if open_:
        p.rect(1, 5, 24, 7, WOOD[0])  # dark inside
        p.poly([(0, 4), (-1, 0), (6, 1), (8, 4)], WOOD[5])
        p.line([(0, 4), (-1, 0), (6, 1)], OUTLINE)
        p.poly([(25, 4), (25, 0), (19, 1), (17, 4)], WOOD[4])
        p.line([(25, 4), (25, 0), (19, 1)], OUTLINE)
    else:
        p.rect(0, 2, 25, 5, WOOD[5], OUTLINE)
        p.rect(11, 2, 14, 7, BEIGE[2])  # tape across the lid
    return p.img


def archive_disk(colours):
    """Blank archive disk (3.5-inch style)."""
    p = Pen((8, 8), colours)
    p.rect(0, 0, 7, 7, NIGHT[2], OUTLINE)
    p.rect(2, 0, 5, 2, METAL[3])  # shutter
    p.px(4, 1, METAL[1])
    p.rect(2, 4, 5, 6, PAPER)  # label
    return p.img


def transfer_device(colours):
    """Second transfer device: a small external drive with a status light."""
    p = Pen((14, 8), colours)
    p.box(0, 1, 13, 7, METAL, mid=1)
    p.line([(2, 3), (8, 3)], METAL[3])
    p.px(11, 3, PHOSPHOR_DIM)
    p.line([(13, 0), (13, 2)], NIGHT[0])  # cable stub
    return p.img


def paper_jam(colours):
    """Crumpled page sticking out of the printer slot (overlay)."""
    p = Pen((14, 6), colours)
    p.poly([(0, 0), (13, 0), (11, 3), (13, 5), (2, 5), (0, 2)], PAPER)
    p.line([(0, 0), (13, 0), (11, 3), (13, 5), (2, 5), (0, 2), (0, 0)], BEIGE[1])
    p.line([(4, 1), (6, 4)], BEIGE[2])
    return p.img


def build_props(colours) -> dict[str, Image.Image]:
    props = {
        "desk": desk(colours),
        "chair": chair(colours),
        "printer_table": printer_table(colours),
        "workbench": workbench(colours),
        "ofrenda_lit": ofrenda(colours, True),
        "ofrenda_unlit": ofrenda(colours, False),
        "keyboard": keyboard(colours),
        "printout": printout(colours),
        "printer_cable": printer_cable(colours),
        "tape": tape(colours),
        "photo": photo(colours),
        "notebook": notebook(colours),
        "paper": paper_ream(colours),
        "cable": cable_coil(colours),
        "headphones": headphones(colours),
        "disk": archive_disk(colours),
        "transfer_device": transfer_device(colours),
        "paper_jam": paper_jam(colours),
    }
    for s in ("off", "on", "message"):
        props[f"crt_{s}"] = crt(colours, s)
    for on in (False, True):
        props[f"speaker_{'on' if on else 'off'}"] = speaker(colours, on)
        for paper in (False, True):
            props[f"printer_{'on' if on else 'off'}_{'loaded' if paper else 'empty'}"] = printer(colours, on, paper)
    for o in (False, True):
        props[f"storage_{'open' if o else 'closed'}"] = storage(colours, o)
    # Hover outlines for everything Marycel can use (not plain furniture).
    for name in [n for n in props if n not in ("desk", "printer_table", "chair", "printer_cable", "paper_jam")]:
        props[f"{name}_outline"] = outline_of(props[name])
    return props
