"""Build the native pixel-art assets and the 640x360 test screens.

Steps: rebuild the shared palette, draw the three room backgrounds, export
Marycel's native sprites, draw the props, compose each room from data/rooms,
render a scrolling test screen per room, then check every native file against the pixel rules and the room data
against data/catalog.json.

Run from the project root:
    .venv/Scripts/python tools/build_pixel_assets.py
"""

from __future__ import annotations

import json
import shutil

from PIL import Image, ImageDraw, ImageFont

import build_character_sprites
import build_props
import build_rooms
import room_data
import pixel_spec as ps

ROOMS_OUT = ps.PIXEL_OUT / "rooms"
PROPS_OUT = ps.PIXEL_OUT / "props"
MOCKUP_OUT = ps.PIXEL_OUT / "mockup"

# Room measurements on the 960x224 grid (shared by all three rooms).
FLOOR_BACK = build_rooms.FLOOR_Y  # where the back wall meets the floor
FURNITURE_BASE = 184  # furniture feet stand on this row
WALK_LANE = 198  # Marycel's feet
DOOR_HEIGHT = 140

OUTLINE, PHOSPHOR, PHOSPHOR_DIM, PAPER = build_props.OUTLINE, build_props.PHOSPHOR, build_props.PHOSPHOR_DIM, build_props.PAPER
PLASTIC = build_props.BEIGE


def frame(name: str, outfit: str = "star-sweater") -> tuple[Image.Image, tuple[int, int]]:
    m = json.loads((build_character_sprites.OUT / "manifest.json").read_text())
    origin = m["outfits"][outfit]["scales"]["native"]["origin"]
    path = build_character_sprites.OUT / outfit / "native" / "frames" / f"{name}.png"
    return Image.open(path).convert("RGBA"), tuple(origin)


def place_sprite(canvas, sprite, origin, foot_x, foot_y, flip=False):
    if flip:
        sprite = sprite.transpose(Image.FLIP_LEFT_RIGHT)
        origin = (sprite.width - origin[0], origin[1])
    canvas.alpha_composite(sprite, (foot_x - origin[0], foot_y - origin[1]))


def compose_scene(colours, name: str, room_img: Image.Image, props) -> tuple[Image.Image, dict]:
    """Objects from data/rooms/<name>.json, plus Marycel at her start spot."""
    scene, room = room_data.compose_scene(colours, name, room_img, props)
    start = next(o for o in room["objects"] if o["id"] == room["marycel_start"]["at"])
    idle, origin = frame("idle_00")
    place_sprite(scene, idle, origin, start["stand_x"], WALK_LANE, flip=room["marycel_start"]["facing"] == "left")
    return scene, room


def camera_x(scene_width: int, focus_x: int) -> int:
    """Left edge of the 640-wide view centred on focus_x, clamped to the room."""
    return min(max(focus_x - ps.SCREEN[0] // 2, 0), scene_width - ps.SCREEN[0])


def hover_demo(colours, scene: Image.Image, room: dict, props, focus_x: int, target: str = "printer") -> None:
    """Draw the hover outline and label the game shows when the player points
    at an object (here the printer), so the cue can be judged in the mockup.
    The label stays inside the view, as the game's will."""
    catalog = room_data.load_catalog()
    obj = next(o for o in room["objects"] if o["id"] == target)
    x0, y0, _, _ = room_data.bounds(obj, catalog, props)
    scene.alpha_composite(props[room_data.sprite_for(obj, catalog) + "_outline"], (x0 - 1, y0 - 1))
    st = obj["state"]
    bits = [st["power"], "paper loaded" if st["paper"] == "loaded" else "no paper"]
    if st["cable"] != "connected":
        bits.append("unplugged")
    if st["jam"] == "yes":
        bits.append("jammed")
    text = "Printer - " + ", ".join(bits)
    d = ImageDraw.Draw(scene)
    d.fontmode = "1"
    font = ImageFont.load_default(size=10)
    # Measure the text as actually drawn without anti-aliasing (textbbox runs narrower).
    probe = Image.new("1", (400, 24))
    pd = ImageDraw.Draw(probe)
    pd.fontmode = "1"
    pd.text((0, 0), text, font=font, fill=1)
    l, t, r, b = probe.getbbox()
    tw = r - l
    cam = camera_x(scene.width, focus_x)
    lx = min(max(x0 + 18 - tw // 2, cam + 6), cam + ps.SCREEN[0] - tw - 6)
    col = lambda rgb: ps.nearest(colours, rgb) + (255,)
    d.rectangle((lx - 4, y0 - 19, lx + tw + 4, y0 - 5), fill=col((12, 8, 10)), outline=col(build_props.HIGHLIGHT))
    d.text((lx - l, y0 - 16 - t), text, font=font, fill=col(build_props.HIGHLIGHT))


def compose_mockup(colours, scene: Image.Image, focus_x: int) -> Image.Image:
    """One game screen: the view centred on focus_x, clamped to the room."""
    screen = Image.new("RGBA", ps.SCREEN, ps.nearest(colours, (14, 12, 16)) + (255,))
    cam = camera_x(scene.width, focus_x)
    screen.alpha_composite(scene.crop((cam, 0, cam + ps.SCREEN[0], scene.height)), (0, 0))

    # Signal panel.
    d = ImageDraw.Draw(screen)
    d.fontmode = "1"  # no anti-aliasing: text stays on the pixel grid
    col = lambda rgb: ps.nearest(colours, rgb) + (255,)
    panel_top = ps.ROOM_SIZE[1]
    d.rectangle((0, panel_top, 639, 359), fill=col((22, 20, 26)))
    d.line((0, panel_top, 639, panel_top), fill=col(OUTLINE))
    d.rectangle((16, 248, 400, 340), fill=col((14, 18, 16)), outline=col(PHOSPHOR_DIM))
    d.rectangle((17, 249, 399, 339), outline=col(PHOSPHOR))
    font = ImageFont.load_default(size=24)
    d.text((34, 278), "WAIT", font=font, fill=col(PHOSPHOR))
    d.rectangle((102, 280, 111, 302), fill=col(PHOSPHOR))
    for i, icon in enumerate(("screen", "speaker", "printer")):
        x0 = 424 + i * 70
        d.rectangle((x0, 262, x0 + 56, 326), fill=col((30, 28, 34)), outline=col(PLASTIC[1]))
        cx, cy = x0 + 28, 294
        if icon == "screen":
            d.rectangle((cx - 14, cy - 11, cx + 14, cy + 9), outline=col(PHOSPHOR), fill=col(PHOSPHOR_DIM))
            d.rectangle((cx - 4, cy + 10, cx + 4, cy + 12), fill=col(PLASTIC[2]))
        elif icon == "speaker":
            d.rectangle((cx - 13, cy - 5, cx - 6, cy + 5), fill=col(PLASTIC[2]))
            d.polygon([(cx - 6, cy - 5), (cx + 2, cy - 12), (cx + 2, cy + 12), (cx - 6, cy + 5)], fill=col(PLASTIC[2]))
            d.line((cx + 6, cy - 6, cx + 6, cy + 6), fill=col(PLASTIC[3]))
            d.line((cx + 10, cy - 10, cx + 10, cy + 10), fill=col(PLASTIC[3]))
        else:
            d.rectangle((cx - 8, cy - 14, cx + 8, cy - 4), fill=col(PAPER))
            d.rectangle((cx - 15, cy - 5, cx + 15, cy + 8), fill=col(PLASTIC[2]), outline=col(OUTLINE))
            d.rectangle((cx - 10, cy + 1, cx + 10, cy + 2), fill=col(OUTLINE))
    return screen


def main() -> None:
    if ps.PIXEL_OUT.exists():
        shutil.rmtree(ps.PIXEL_OUT)
    colours = ps.build_palette()
    ps.save_palette(colours)

    ROOMS_OUT.mkdir(parents=True)
    rooms = {}
    for name in build_rooms.ROOMS:
        rooms[name] = build_rooms.draw(name, colours)
        rooms[name].save(ROOMS_OUT / f"{name}.png")

    build_character_sprites.main()

    PROPS_OUT.mkdir(parents=True)
    props = build_props.build_props(colours)
    for name, img in props.items():
        img.save(PROPS_OUT / f"{name}.png")

    MOCKUP_OUT.mkdir(parents=True)
    for name, room in rooms.items():
        scene, room_json = compose_scene(colours, name, room, props)
        scene.save(MOCKUP_OUT / f"{name}-room.png")
        start = next(o for o in room_json["objects"] if o["id"] == room_json["marycel_start"]["at"])
        hover_demo(colours, scene, room_json, props, start["stand_x"])
        mock = compose_mockup(colours, scene, start["stand_x"])
        mock.save(MOCKUP_OUT / f"{name}-640x360.png")
        for k in ps.DISPLAY_SCALES:
            mock.resize((640 * k, 360 * k), Image.NEAREST).save(
                MOCKUP_OUT / f"{name}-{640 * k}x{360 * k}.png")

    # Rule check over every native asset.
    files = sorted(ROOMS_OUT.glob("*.png")) + sorted(PROPS_OUT.glob("*.png"))
    files += sorted(build_character_sprites.OUT.glob("*/native/**/*.png"))
    files += sorted(MOCKUP_OUT.glob("*-640x360.png")) + sorted(MOCKUP_OUT.glob("*-room.png"))
    failures = {f: ps.check(Image.open(f), colours) for f in files}
    failures = {f: p for f, p in failures.items() if p}
    print(f"palette: {len(colours)} colours")
    print(f"checked {len(files)} native files: {len(failures)} failing")
    for f, p in failures.items():
        print(f"  {f.relative_to(ps.ROOT)}: {'; '.join(p)}")
    problems = room_data.check_all(props)
    n = sum(map(len, problems.values()))
    print(f"room data: {n} problems")
    for k, v in problems.items():
        for q in v:
            print(f"  {k}: {q}")
    if failures or n:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
