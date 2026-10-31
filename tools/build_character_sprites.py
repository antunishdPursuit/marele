"""Build game-ready Marycel sprites from the concept character sheets.

Each source sheet holds six side-view poses in the same order:
idle, walk contact A, walk contact B, sit/type, crouch-reach, read paper.
An outfit can add pose sheets (EXTRA_SHEETS): six more poses each, the first a
plain standing pose that sets their scale to match the main sheet.

The script cuts the poses apart, cleans the noisy AI alpha, aligns every pose
to a shared foot anchor, builds the animation sequences (walk, pick up, sit,
read, idle), and writes per-frame PNGs, horizontal sprite sheets, a JSON
manifest, and GIF previews for each outfit and export scale.

Run from the project root:
    .venv/Scripts/python tools/build_character_sprites.py
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import pixel_spec

ROOT = Path(__file__).resolve().parent.parent
CONCEPT = ROOT / "assets" / "concept-art"
OUT = ROOT / "assets" / "sprites" / "marycel"

# outfit -> (sheet, (seam, warm band end)) for the synthesized walk passing
# frame, as fractions of figure height. The skirt hides the stride, so the
# sweater seam sits at the hem; the cardigan seam sits at the hip and the warm
# band carries the hanging hands and knit hem down over the straight jeans.
OUTFITS = {
    "star-sweater": ("Marycel - Star Sweater Character Sheet.png", (0.80, 0.80)),
    "green-cardigan": ("Hacktoberfest Week 4 - Marycel Character Concept.png", (0.52, 0.66)),
}
POSE_NAMES = ["idle", "walk_a", "walk_b", "sit_type", "crouch_reach", "read"]

# Extra pose sheets, made with image generation from the main sheet. The first
# pose of each is a standing reference that is scaled to the main idle height.
EXTRA_SHEETS = {
    "star-sweater": [
        ("Marycel - Star Sweater Poses A.png",
         ["ref_a", "pull_chair", "sit_lower", "sit_idle", "sit_reach", "reach_desk"]),
        ("Marycel - Star Sweater Poses B.png",
         ["ref_b", "lean_inspect", "write", "headphones", "kneel", "kneel_reach"]),
    ],
}

# Export scales: label -> target standing height in pixels.
# "hd" is a smooth reference matching the room concept (1672 px wide scene).
# "native" is the game asset: on the 640x360 grid, snapped to the shared
# palette (see pixel_spec.py). Only "native" follows the pixel rules.
SCALES = {"hd": 320, "native": pixel_spec.CHARACTER_HEIGHT}
QUANTIZED = {"native"}
PREVIEW_ZOOM = {"native": 3}

ALPHA_CUT = 128  # source alpha is ~250 for solid pixels and noisy below
MIN_SPECK = 60  # drop isolated alpha islands smaller than this (source px)


@dataclass
class Pose:
    name: str
    image: Image.Image  # RGBA, cleaned, trimmed
    anchor_x: int  # foot centre, in image coordinates
    # baseline is always the bottom row of the image


# ---------------------------------------------------------------- extraction


def column_runs(mask: np.ndarray, min_gap: int = 8) -> list[tuple[int, int]]:
    occupied = mask.any(axis=0)
    runs, start, gap = [], None, 0
    for x, v in enumerate(occupied):
        if v:
            if start is None:
                start = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                runs.append((start, x - gap + 1))
                start, gap = None, 0
    if start is not None:
        runs.append((start, len(occupied)))
    return runs


def label_components(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """4-connected component labels without scipy (union-find over runs)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    parent = [0]

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y in range(h):
        row = mask[y]
        x = 0
        while x < w:
            if not row[x]:
                x += 1
                continue
            x0 = x
            while x < w and row[x]:
                x += 1
            above = set(labels[y - 1, x0:x][labels[y - 1, x0:x] > 0]) if y else set()
            if above:
                roots = sorted({find(int(a)) for a in above})
                lab = roots[0]
                for r in roots[1:]:
                    parent[r] = lab
            else:
                lab = len(parent)
                parent.append(lab)
            labels[y, x0:x] = lab
    roots = np.array([find(i) for i in range(len(parent))], dtype=np.int32)
    labels = roots[labels]
    sizes = np.bincount(labels.ravel(), minlength=len(parent))
    return labels, sizes


def drop_edge_scraps(rgba: np.ndarray, share: float = 0.15) -> np.ndarray:
    """Remove pieces of a neighbouring pose (a reaching hand) that a crop caught at its sides."""
    labels, sizes = label_components(rgba[..., 3] > 0)
    biggest = sizes[1:].max() if len(sizes) > 1 else 0
    out = rgba.copy()
    for lab in set(labels[:, 0]) | set(labels[:, -1]):
        if lab and sizes[lab] < biggest * share:
            out[labels == lab] = 0
    return out


def clean_alpha(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[..., 3] >= ALPHA_CUT
    labels, sizes = label_components(alpha)
    keep = sizes >= MIN_SPECK
    keep[0] = False
    alpha = keep[labels]
    # Close pinholes inside the figure.
    a_img = Image.fromarray((alpha * 255).astype(np.uint8))
    a_img = a_img.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    alpha = np.array(a_img) > 127
    out = rgba.copy()
    out[..., 3] = np.where(alpha, 255, 0)
    out[~alpha, :3] = 0
    return out


def defringe(rgba: np.ndarray) -> np.ndarray:
    """Replace edge pixels whose colour bled from the source background.

    The generator left a reddish/olive halo around hair and shoes. Edge pixels
    that are far brighter or more saturated than their inner neighbours take
    the average colour of the opaque pixels one step inward.
    """
    alpha = rgba[..., 3] > 0
    inner = np.array(
        Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))
    ) > 0
    edge = alpha & ~inner
    rgb = rgba[..., :3].astype(np.float32)
    acc = np.zeros_like(rgb)
    cnt = np.zeros(alpha.shape, np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == dy == 0:
                continue
            m = np.roll(np.roll(inner, dy, 0), dx, 1)
            c = np.roll(np.roll(rgb, dy, 0), dx, 1)
            acc += c * m[..., None]
            cnt += m
    has = edge & (cnt > 0)
    avg = acc / np.maximum(cnt, 1)[..., None]
    diff = np.abs(rgb - avg).sum(-1)
    fix = has & (diff > 90)
    out = rgba.copy()
    out[fix, :3] = avg[fix].astype(np.uint8)
    # Darken the outer edge a touch so the silhouette reads as an outline.
    out[edge, :3] = (out[edge, :3].astype(np.float32) * 0.8).astype(np.uint8)
    return out


def trim(rgba: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(rgba[..., 3])
    return rgba[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def foot_anchor(rgba: np.ndarray, band: float = 0.07) -> int:
    """Horizontal centre of the opaque pixels in the bottom band (the feet)."""
    h = rgba.shape[0]
    rows = rgba[int(h * (1 - band)) :, :, 3] > 0
    xs = np.nonzero(rows)[1]
    return int(round((xs.min() + xs.max()) / 2))


def extract_poses(sheet_path: Path, names: list[str] = POSE_NAMES) -> list[Pose]:
    rgba = np.array(Image.open(sheet_path).convert("RGBA"))
    runs = column_runs(rgba[..., 3] >= ALPHA_CUT)
    runs = [r for r in runs if r[1] - r[0] > 80]
    # poses that touch (an outstretched arm) are split at the thinnest column of the widest run
    counts = (rgba[..., 3] >= ALPHA_CUT).sum(0)
    while len(runs) < len(names):
        x0, x1 = max(runs, key=lambda r: r[1] - r[0])
        lo, hi = x0 + (x1 - x0) // 5, x1 - (x1 - x0) // 5
        cut = lo + int(np.argmin(counts[lo:hi]))
        i = runs.index((x0, x1))
        runs[i:i + 1] = [(x0, cut), (cut + 1, x1)]
    if len(runs) != len(names):
        raise SystemExit(f"{sheet_path.name}: expected {len(names)} poses, found {len(runs)}: {runs}")
    poses = []
    for name, (x0, x1) in zip(names, runs):
        crop = drop_edge_scraps(clean_alpha(rgba[:, max(0, x0 - 4) : x1 + 4]))
        crop = trim(defringe(crop))
        poses.append(Pose(name, Image.fromarray(crop), foot_anchor(crop)))
    return poses


# ------------------------------------------------------------ synthesis


def passing_pose(walk: Pose, idle: Pose, seam: float, warm_band_end: float) -> Pose:
    """Mid-stride passing frame: walk upper body over the idle (feet-together) legs.

    Rows above `seam` come from the walk pose. Between `seam` and
    `warm_band_end` only the walk's warm-coloured pixels are kept (see below).
    """
    w = np.array(walk.image)
    i = np.array(idle.image)
    cut_w = int(w.shape[0] * seam)
    cut_i = int(i.shape[0] * seam)
    upper = w[:cut_w]
    lower = i[cut_i:]
    # Align upper body horizontally on the walk anchor, legs on the idle anchor.
    width = 2 * (upper.shape[1] + lower.shape[1])
    cx = width // 2
    canvas = np.zeros((upper.shape[0] + lower.shape[0], width, 4), np.uint8)
    lx = cx - idle.anchor_x
    canvas[upper.shape[0] :, lx : lx + lower.shape[1]] = lower
    # The torso leans forward in the walk pose; anchor it on the waist centre.
    waist_row = upper[-1, :, 3] > 0
    wx = np.nonzero(waist_row)[0]
    low_row = lower[0, :, 3] > 0
    lxs = np.nonzero(low_row)[0]
    ux = (lx + (lxs.min() + lxs.max()) // 2) - (wx.min() + wx.max()) // 2
    region = canvas[: upper.shape[0], ux : ux + upper.shape[1]]
    m = upper[..., 3] > 0
    region[m] = upper[m]
    # Below the seam, keep only the walk's warm pixels (hands, knit hem) over
    # the idle legs, so a swinging hand that hangs past the seam survives while
    # the striding cool-toned trousers are replaced. Plus 3 rows of overlap.
    band_end = max(cut_w + 3, int(w.shape[0] * warm_band_end))
    band = w[cut_w:band_end].astype(np.int16)
    warm = (band[..., :3].max(-1) - band[..., 2] > 18) & (band[..., 3] > 0)
    # Morphological opening drops 1-2 px strands of the source's orange halo.
    wimg = Image.fromarray((warm * 255).astype(np.uint8))
    warm = np.array(wimg.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))) > 0
    warm[:3] |= band[:3, :, 3] > 0
    breg = canvas[cut_w : cut_w + band.shape[0], ux : ux + band.shape[1]]
    warm[:3] &= breg[:3, :, 3] > 0
    breg[warm] = band[warm].astype(np.uint8)
    labels, sizes = label_components(canvas[..., 3] > 0)
    canvas[(sizes < MIN_SPECK)[labels]] = 0
    img = trim(canvas)
    return Pose(f"{walk.name}_pass", Image.fromarray(img), foot_anchor(img))


def squash(pose: Pose, sy: float, sx: float = 1.0, name: str | None = None) -> Pose:
    """Scale from the feet (anticipation / settle frames)."""
    w, h = pose.image.size
    nw, nh = max(1, round(w * sx)), max(1, round(h * sy))
    img = pose.image.resize((nw, nh), Image.NEAREST)
    return Pose(name or pose.name, img, round(pose.anchor_x * sx))


# ---------------------------------------------------------------- animation

# Each frame: (pose name, dx, dy, duration ms). dy < 0 lifts the sprite.
# Events mark gameplay hooks (e.g. when the item should leave the floor).


def animations() -> dict[str, dict]:
    return {
        "idle": {
            "loop": True,
            "frames": [("idle", 0, 0, 600), ("idle_breathe", 0, 0, 500)],
        },
        "walk": {
            "loop": True,
            "frames": [
                ("walk_a", 0, 0, 120),
                ("walk_a_pass", 0, -1, 120),
                ("walk_b", 0, 0, 120),
                ("walk_b_pass", 0, -1, 120),
            ],
        },
        "pickup": {
            "loop": False,
            "events": {"grab": 5, "item_in_hand": 7},
            "frames": [
                ("idle", 0, 0, 120),
                ("idle_dip", 0, 0, 90),  # anticipation
                ("crouch_drop", 0, 0, 80),  # mid-descent
                ("crouch_land", 0, 0, 90),  # settle squash
                ("crouch_reach", 0, 0, 140),
                ("crouch_reach", 0, 0, 260),  # grab
                ("crouch_drop", 0, 0, 100),  # rising
                ("idle_dip", 0, 0, 90),
                ("idle", 0, 0, 160),
            ],
        },
        "pickup_and_read": {
            "loop": False,
            "events": {"grab": 5, "item_in_hand": 7},
            "frames": [
                ("idle", 0, 0, 120),
                ("idle_dip", 0, 0, 90),
                ("crouch_drop", 0, 0, 80),
                ("crouch_land", 0, 0, 90),
                ("crouch_reach", 0, 0, 140),
                ("crouch_reach", 0, 0, 260),
                ("crouch_drop", 0, 0, 100),
                ("idle_dip", 0, 0, 90),
                ("read", 0, 0, 900),
            ],
        },
        "read": {
            "loop": True,
            "frames": [("read", 0, 0, 700), ("read_breathe", 0, 0, 600)],
        },
        "sit_type": {
            "loop": True,
            "frames": [("sit_type", 0, 0, 160), ("sit_type", 0, -1, 160)],
        },
    }


# Animations built from the extra pose sheets. "chair" events say when the chair
# starts and stops moving (frame indexes), so the game can slide it with her hands.
EXTRA_ANIMATIONS = {
    # Pulling the chair out (or pushing it back in): her hands stay on the backrest while the
    # game slides her and the chair together between the "chair" events.
    "pull_chair": {
        "loop": False,
        "events": {"chair_start": 1, "chair_end": 3},
        "frames": [("idle_dip", 0, 0, 100), ("pull_chair", 0, 0, 260), ("pull_chair", 0, -1, 260),
                   ("pull_chair", 0, 0, 120)],
    },
    "sit_down": {  # backing down onto the chair behind her
        "loop": False,
        "frames": [("idle", 0, 0, 100), ("idle_dip", 0, 0, 90), ("sit_lower", 0, 0, 200),
                   ("sit_idle", -2, 1, 90), ("sit_idle", -2, 0, 160)],
    },
    "stand_up": {
        "loop": False,
        "frames": [("sit_idle", -2, 0, 100), ("sit_lower", 0, 0, 220), ("idle_dip", 0, 0, 120), ("idle", 0, 0, 120)],
    },
    # Seated poses shift so her hips stay where sit_type puts them.
    "sit_idle": {"loop": True, "frames": [("sit_idle", -2, 0, 900), ("sit_idle_breathe", -2, 0, 700)]},
    "sit_reach": {
        "loop": False,
        "frames": [("sit_idle", -2, 0, 120), ("sit_reach", -3, 0, 200), ("sit_reach", -3, 0, 500),
                   ("sit_idle", -2, 0, 300)],
    },
    "reach_desk": {
        "loop": False,
        "events": {"grab": 2},
        "frames": [("idle", 0, 0, 100), ("idle_dip", 0, 0, 90), ("reach_desk", 0, 0, 600),
                   ("idle_dip", 0, 0, 90), ("idle", 0, 0, 200)],
    },
    "inspect": {"loop": True, "frames": [("lean_inspect", 0, 0, 800), ("lean_inspect_breathe", 0, 0, 700)]},
    "write": {"loop": True, "frames": [("write", 0, 0, 500), ("write_breathe", 0, 0, 400)]},
    "headphones": {
        "loop": False,
        "frames": [("idle", 0, 0, 120), ("headphones", 0, 0, 600), ("idle", 0, 0, 200)],
    },
    "kneel": {  # down through the crouch, a moment at the ofrenda, and up again
        "loop": False,
        "frames": [("idle", 0, 0, 120), ("idle_dip", 0, 0, 100), ("crouch_drop", 0, 0, 110),
                   ("kneel", 0, 0, 1400), ("kneel_breathe", 0, 0, 1000), ("crouch_drop", 0, 0, 120),
                   ("idle_dip", 0, 0, 100), ("idle", 0, 0, 200)],
    },
}


def extra_poses(outfit: str, idle_h: int) -> list[Pose]:
    """The outfit's extra sheets, each scaled so its standing reference matches idle."""
    out = []
    for filename, names in EXTRA_SHEETS.get(outfit, []):
        poses = extract_poses(CONCEPT / filename, names)
        factor = idle_h / poses[0].image.size[1]
        for p in poses[1:]:
            w, h = p.image.size
            img = p.image.resize((round(w * factor), round(h * factor)), Image.LANCZOS)
            arr = np.array(img)
            arr[..., 3] = np.where(arr[..., 3] >= ALPHA_CUT, 255, 0)
            arr = trim(arr)
            out.append(Pose(p.name, Image.fromarray(arr), foot_anchor(arr)))
    return out


def build_pose_library(poses: list[Pose], seam: tuple[float, float]) -> dict[str, Pose]:
    lib = {p.name: p for p in poses}
    lib["walk_a_pass"] = passing_pose(lib["walk_a"], lib["idle"], *seam)
    lib["walk_b_pass"] = passing_pose(lib["walk_b"], lib["idle"], *seam)
    lib["idle_breathe"] = squash(lib["idle"], 0.99, 1.005, "idle_breathe")
    lib["read_breathe"] = squash(lib["read"], 0.99, 1.005, "read_breathe")
    lib["idle_dip"] = squash(lib["idle"], 0.95, 1.02, "idle_dip")
    # Descent in-between: the crouch, stretched upward partway to standing.
    stand_h = lib["idle"].image.size[1]
    crouch_h = lib["crouch_reach"].image.size[1]
    mid = (stand_h * 0.35 + crouch_h * 0.65) / crouch_h
    lib["crouch_drop"] = squash(lib["crouch_reach"], mid, 0.97, "crouch_drop")
    lib["crouch_land"] = squash(lib["crouch_reach"], 0.96, 1.03, "crouch_land")
    for name in ("sit_idle", "write", "lean_inspect", "kneel"):
        if name in lib:
            lib[name + "_breathe"] = squash(lib[name], 0.99, 1.005, name + "_breathe")
    return lib


# ------------------------------------------------------------------- output


def scale_pose(pose: Pose, factor: float) -> Pose:
    w, h = pose.image.size
    nw, nh = max(1, round(w * factor)), max(1, round(h * factor))
    # Box-filter colour on premultiplied pixels, then hard alpha for crisp edges.
    arr = np.array(pose.image).astype(np.float32)
    a = arr[..., 3:] / 255
    pre = np.concatenate([arr[..., :3] * a, a * 255], -1).astype(np.uint8)
    small = np.array(Image.fromarray(pre).resize((nw, nh), Image.BOX)).astype(np.float32)
    sa = small[..., 3:]
    rgb = np.where(sa > 0, small[..., :3] * 255 / np.maximum(sa, 1), 0)
    out = np.concatenate([rgb, np.where(sa >= 110, 255, 0)], -1)
    out[out[..., 3] == 0, :3] = 0
    return Pose(pose.name, Image.fromarray(out.clip(0, 255).astype(np.uint8)), round(pose.anchor_x * factor))


def export_outfit(outfit: str, lib: dict[str, Pose]) -> dict:
    anims = animations()
    anims.update({k: v for k, v in EXTRA_ANIMATIONS.items() if all(f[0] in lib for f in v["frames"])})
    stand_h = lib["idle"].image.size[1]
    manifest = {"outfit": outfit, "scales": {}}
    for label, target_h in SCALES.items():
        factor = target_h / stand_h
        scaled = {k: scale_pose(p, factor) for k, p in lib.items()}
        if label in QUANTIZED:
            colours = pixel_spec.load_palette()
            for p in scaled.values():
                p.image = pixel_spec.quantize(p.image, colours)
        zoom = PREVIEW_ZOOM.get(label, 1)
        # One cell size for every frame so engines can use a fixed grid.
        pad = max(2, round(4 * factor * 4))
        left = max(p.anchor_x for p in scaled.values()) + pad
        right = max(p.image.size[0] - p.anchor_x for p in scaled.values()) + pad
        top = max(p.image.size[1] for p in scaled.values()) + pad
        cell_w, cell_h = left + right, top + pad // 2
        base_y = top  # feet rest on this row (exclusive)
        out_dir = OUT / outfit / label
        frames_dir = out_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        info = {
            "cell": [cell_w, cell_h],
            "origin": [left, base_y],
            "origin_note": "pixel position of the feet centre inside each cell; place this on the floor point",
            "animations": {},
        }
        for anim_name, spec in anims.items():
            cells, gif_frames, durations = [], [], []
            for idx, (pname, dx, dy, ms) in enumerate(spec["frames"]):
                p = scaled[pname]
                cell = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
                ox = left - p.anchor_x + dx
                oy = base_y - p.image.size[1] + dy
                cell.alpha_composite(p.image, (ox, oy))
                cell.save(frames_dir / f"{anim_name}_{idx:02d}.png")
                cells.append(cell)
                durations.append(ms)
            sheet = Image.new("RGBA", (cell_w * len(cells), cell_h), (0, 0, 0, 0))
            for i, c in enumerate(cells):
                sheet.alpha_composite(c, (i * cell_w, 0))
            sheet.save(out_dir / f"{anim_name}.png")
            # GIF preview on the room's dark floor colour.
            bg = (38, 32, 30, 255)
            for c in cells:
                g = Image.new("RGBA", c.size, bg)
                g.alpha_composite(c)
                g = g.resize((g.width * zoom, g.height * zoom), Image.NEAREST)
                gif_frames.append(g.convert("RGB"))
            gif_frames[0].save(
                out_dir / f"{anim_name}_preview.gif",
                save_all=True,
                append_images=gif_frames[1:],
                duration=durations,
                loop=0,
                disposal=2,
            )
            info["animations"][anim_name] = {
                "sheet": f"{anim_name}.png",
                "frame_count": len(cells),
                "durations_ms": durations,
                "loop": spec["loop"],
                "events": spec.get("events", {}),
                "faces": "right",
            }
        manifest["scales"][label] = info
    return manifest


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    full = {"character": "Marycel", "generated_by": "tools/build_character_sprites.py",
            "flip_for_left": "Mirror horizontally; the origin x becomes cell_width - origin_x.",
            "outfits": {}}
    for outfit, (filename, seam) in OUTFITS.items():
        poses = extract_poses(CONCEPT / filename)
        poses += extra_poses(outfit, poses[0].image.size[1])
        lib = build_pose_library(poses, seam)
        full["outfits"][outfit] = export_outfit(outfit, lib)
        print(f"{outfit}: {', '.join(full['outfits'][outfit]['scales'])} exported")
    (OUT / "manifest.json").write_text(json.dumps(full, indent=2))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
