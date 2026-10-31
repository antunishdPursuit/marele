"""Load, check and draw the room data in data/.

data/catalog.json holds the shared rules (object kinds, states, sprites,
Marycel's actions, Elena's signals). data/rooms/<room>.json places each
room's objects and items. The art builder composes scenes from these files,
so the picture and the game data always agree.

    .venv/Scripts/python tools/room_data.py   # check the data only
"""

from __future__ import annotations

import json

import numpy as np
from PIL import Image

import build_rooms
import pixel_spec as ps

DATA = ps.ROOT / "data"
FLOOR_ITEM_BASE = 194  # items lying on the floor rest on this row


def load_catalog() -> dict:
    return json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))


def load_room(name: str) -> dict:
    return json.loads((DATA / "rooms" / f"{name}.json").read_text(encoding="utf-8"))


def sprite_for(obj: dict, catalog: dict) -> str | None:
    """First sprite rule whose conditions match the object's state."""
    state = obj.get("state", {})
    for rule in catalog["kinds"][obj["kind"]]["sprites"]:
        if all(state.get(k) == v for k, v in rule.get("when", {}).items()):
            return rule["sprite"].format(**state)
    return None


def overlays_for(obj: dict, catalog: dict) -> list[dict]:
    state = obj.get("state", {})
    return [o for o in catalog["kinds"][obj["kind"]].get("overlays", [])
            if all(state.get(k) == v for k, v in o["when"].items())]


def bounds(obj: dict, catalog: dict, props: dict) -> tuple[int, int, int, int]:
    """Hover box (x0, y0, x1, y1) in room pixels."""
    if obj["kind"] == "window":
        x0, y0, x1, y1 = build_rooms.WINDOW
        return x0 - 5, y0 - 5, x1 + 5, y1 + 8
    if obj["kind"] == "door":
        d0, d1 = build_rooms.DOOR_X
        top = round(build_rooms.BOT_F[d1] - build_rooms.DOOR_FRACTION * (build_rooms.BOT_F[d1] - build_rooms.TOP_F[d1]))
        return d0 - 3, top - 3, d1 + 3, int(build_rooms.BOT[d1])
    img = props[sprite_for(obj, catalog)]
    return obj["x"], obj["base"] - img.height, obj["x"] + img.width - 1, obj["base"] - 1


def item_position(item: dict, room: dict, catalog: dict, props: dict) -> tuple[int, int] | None:
    """Top-left of a visible item, or None when it is inside a container."""
    if "in" in item:
        return None
    img = props[catalog["items"][item["kind"]]["sprite"]]
    if "floor_x" in item:
        return item["floor_x"], FLOOR_ITEM_BASE - img.height
    host_id, slot = item["on"]
    host = next(o for o in room["objects"] if o["id"] == host_id)
    dx, dy = catalog["kinds"][host["kind"]]["slots"][slot]
    host_top = bounds(host, catalog, props)[1]
    return host["x"] + dx, host_top + dy - img.height


# ------------------------------------------------------------------ checks


def check_room(room: dict, catalog: dict, props: dict) -> list[str]:
    problems = []
    kinds = catalog["kinds"]
    objs = {o["id"]: o for o in room["objects"]}
    lo, hi = catalog["walk_range"]
    w, h = ps.ROOM_SIZE
    for o in room["objects"]:
        k = kinds.get(o["kind"])
        if k is None:
            problems.append(f"{o['id']}: unknown kind {o['kind']}")
            continue
        for s, v in o.get("state", {}).items():
            if v not in k["states"].get(s, []):
                problems.append(f"{o['id']}: state {s}={v} not allowed")
        missing = set(k["states"]) - set(o.get("state", {}))
        if missing:
            problems.append(f"{o['id']}: missing states {sorted(missing)}")
        if k["sprites"]:
            name = sprite_for(o, catalog)
            if name not in props:
                problems.append(f"{o['id']}: no sprite {name}")
                continue
            x0, y0, x1, y1 = bounds(o, catalog, props)
            if x0 < 0 or y0 < 0 or x1 >= w or y1 >= h:
                problems.append(f"{o['id']}: outside the room {x0, y0, x1, y1}")
            for ov in overlays_for(o, catalog):
                if ov["sprite"] not in props:
                    problems.append(f"{o['id']}: no overlay sprite {ov['sprite']}")
        if not k.get("furniture"):
            if "stand_x" not in o:
                problems.append(f"{o['id']}: no stand_x for Marycel")
            elif not lo <= o["stand_x"] <= hi:
                problems.append(f"{o['id']}: stand_x {o['stand_x']} outside walk range {lo}-{hi}")
            if o.get("facing") not in ("left", "right"):
                problems.append(f"{o['id']}: facing must be left or right")
    used_slots = set()
    for it in room["items"]:
        if it["kind"] not in catalog["items"]:
            problems.append(f"{it['id']}: unknown item kind {it['kind']}")
        if "in" in it:
            host = objs.get(it["in"])
            if host is None or not kinds[host["kind"]].get("container"):
                problems.append(f"{it['id']}: 'in' must name a container")
        elif "on" in it:
            host = objs.get(it["on"][0])
            if host is None or it["on"][1] not in kinds[host["kind"]].get("slots", {}):
                problems.append(f"{it['id']}: no slot {it['on']}")
            elif tuple(it["on"]) in used_slots:
                problems.append(f"{it['id']}: slot {it['on']} already used")
            used_slots.add(tuple(it["on"]))
        elif "floor_x" not in it:
            problems.append(f"{it['id']}: needs in, on or floor_x")
    # Every room needs the PRD's shared inventory.
    have = {o["kind"] for o in room["objects"]} | {i["kind"] for i in room["items"]}
    printer = next((o for o in room["objects"] if o["kind"] == "printer"), None)
    if printer and printer["state"].get("cable") == "connected":
        have.add("cable")
    if printer and printer["state"].get("paper") == "loaded":
        have.add("paper")
    for need in catalog["required_inventory"]:
        if not any(n in have for n in need.split("|")):
            problems.append(f"missing required {need}")
    if sum(i["kind"] == "recording" for i in room["items"]) != 1:
        problems.append("there must be exactly one family recording")
    streams = catalog["world"]["states"]["selected_stream"]
    if room.get("hidden", {}).get("elena_stream") not in [s for s in streams if s != "none"]:
        problems.append("hidden.elena_stream must be one of the recovery-map streams")
    for o in room["objects"]:
        if "sit_x" in o and not lo <= o["sit_x"] <= hi:
            problems.append(f"{o['id']}: sit_x {o['sit_x']} outside walk range")
    start = room["marycel_start"]["at"]
    if start not in objs:
        problems.append(f"marycel_start: unknown object {start}")
    return problems


COND_KEYS = {"state", "device", "world", "marycel", "holding", "item_in_target", "item_state", "unlocked", "any",
             "free_slot"}
EFFECT_KEYS = {"state", "device", "world", "marycel", "take", "put_held", "consume_held", "create_held", "item_state",
               "move_held_to"}
SPECIAL_VALUES = {"+1", "-1", "$choice"}
EXPORTED_ANIMS = {"walk", "idle", "pickup", "read", "sit_type"}


def _check_values(where, allowed, values, problems):
    for v in values if isinstance(values, list) else [values]:
        if v not in allowed and v not in SPECIAL_VALUES:
            problems.append(f"{where}: value {v!r} not in {allowed}")


def _check_terms(where, terms, target_kinds, catalog, problems, effect=False):
    """Every state a condition reads or an effect writes must exist with an allowed value."""
    kinds, world, items = catalog["kinds"], catalog["world"]["states"], catalog["items"]
    mstates = catalog["marycel"]["states"]
    keys = EFFECT_KEYS if effect else COND_KEYS
    for t in terms:
        if not set(t) & keys:
            problems.append(f"{where}: unknown term {t}")
            continue
        # Conditions test 'is' (or 'not'); effects write 'set'.
        v = t.get("set") if effect else t.get("is", t.get("not"))
        if any(k in t for k in ("device", "state", "world", "item_state", "marycel")) and v is None:
            problems.append(f"{where}: term {t} has no value")
            continue
        if "any" in t:
            for branch in t["any"]:
                _check_terms(where, branch, target_kinds, catalog, problems)
        elif "device" in t:
            states = kinds.get(t["device"], {}).get("states", {})
            if t["state"] not in states:
                problems.append(f"{where}: {t['device']} has no state {t['state']}")
            else:
                _check_values(where, states[t["state"]], v, problems)
        elif "state" in t:
            for k in target_kinds:
                states = kinds[k]["states"]
                if t["state"] not in states:
                    problems.append(f"{where}: {k} has no state {t['state']}")
                else:
                    _check_values(where, states[t["state"]], v, problems)
        elif "world" in t:
            if t["world"] not in world:
                problems.append(f"{where}: no world state {t['world']}")
            else:
                _check_values(where, world[t["world"]], v, problems)
        elif "marycel" in t:
            allowed = mstates.get(t["marycel"])
            if not isinstance(allowed, list):
                problems.append(f"{where}: Marycel has no state {t['marycel']}")
            else:
                _check_values(where, allowed, v, problems)
        elif "item_state" in t:
            item, st = t["item_state"].split(".")
            allowed = items.get(item, {}).get("states", {}).get(st)
            if allowed is None:
                problems.append(f"{where}: item {item} has no state {st}")
            else:
                _check_values(where, allowed, v, problems)
        elif "unlocked" in t and t["unlocked"] not in catalog["unlocks"]:
            problems.append(f"{where}: unknown unlock {t['unlocked']}")
        for key in ("take", "create_held"):
            if key in t and t[key] != "*" and t[key] not in items:
                problems.append(f"{where}: unknown item {t[key]}")


def _check_rule(where, a, targets, catalog, problems, action_ids):
    """Requirements, effects, conditional and completion effects of one action or signal."""
    _check_terms(where, a.get("requires", []), targets, catalog, problems)
    _check_terms(where, a.get("effects", []), targets, catalog, problems, effect=True)
    for key in ("on_complete", "on_fail"):
        _check_terms(f"{where} {key}", a.get(key, []), targets, catalog, problems, effect=True)
    for branch in a.get("effects_if", []):
        _check_terms(f"{where} effects_if", branch["when"], targets, catalog, problems)
        _check_terms(f"{where} effects_if", branch["effects"], targets, catalog, problems, effect=True)
    for kind, terms in a.get("requires_by_kind", {}).items():
        if kind not in catalog["kinds"]:
            problems.append(f"{where}: requires_by_kind names unknown kind {kind}")
        else:
            _check_terms(f"{where} ({kind})", terms, [kind], catalog, problems)
    for other in a.get("interrupted_by", []):
        if other not in action_ids:
            problems.append(f"{where}: interrupted_by names unknown action {other}")
    if ("on_complete" in a) != ("interrupted_by" in a):
        problems.append(f"{where}: a long action needs both on_complete and interrupted_by")
    for t in a.get("effects", []):
        if t.get("set") != "$choice":
            continue
        if not a.get("choices"):
            problems.append(f"{where}: sets $choice but lists no choices")
        elif "world" in t and not set(a["choices"]) <= set(catalog["world"]["states"][t["world"]]):
            problems.append(f"{where}: choices {a['choices']} are not all values of story {t['world']}")
    if a.get("choices") and a.get("params", {}).get("choice", a["choices"]) != a["choices"]:
        problems.append(f"{where}: params choice differs from choices")


def check_catalog(catalog: dict) -> list[str]:
    problems = []
    kinds = set(catalog["kinds"]) | {"floor"}
    ids = [a["id"] for a in catalog["actions"]]
    sids = [s["id"] for s in catalog["signals"]]
    if len(ids) != len(set(ids)) or len(sids) != len(set(sids)):
        problems.append("duplicate action or signal ids")
    if set(ids) & set(sids):
        problems.append(f"action and signal ids overlap: {sorted(set(ids) & set(sids))}")
    for a in catalog["actions"]:
        if a["kinds"] != "*" and not set(a["kinds"]) <= kinds:
            problems.append(f"action {a['id']}: unknown kinds {set(a['kinds']) - kinds}")
            continue
        if a["anim"] not in EXPORTED_ANIMS:
            problems.append(f"action {a['id']}: animation {a['anim']} is not exported")
        if "params" not in a:
            problems.append(f"action {a['id']}: no params")
        targets = [] if a["kinds"] == "*" else [k for k in a["kinds"] if k != "floor"]
        _check_rule(f"action {a['id']}", a, targets, catalog, problems, set(ids))
    for s in catalog["signals"]:
        if s["device"] not in kinds:
            problems.append(f"signal {s['id']}: unknown device {s['device']}")
            continue
        if s["unlock"] not in catalog["unlocks"]:
            problems.append(f"signal {s['id']}: unknown unlock {s['unlock']}")
        _check_rule(f"signal {s['id']}", s, [s["device"]], catalog, problems, set(ids))
    for name, u in catalog["unlocks"].items():
        rule = u["rule"]
        if isinstance(rule, dict) and "after_any" in rule:
            problems += [f"unlock {name}: unknown action {x}" for x in rule["after_any"] if x not in ids]
        elif isinstance(rule, dict):
            _check_terms(f"unlock {name}", [rule], [], catalog, problems)
    for e in catalog.get("echo", {}).get("events", []):
        _check_terms(f"echo {e['id']}", e["requires"], [], catalog, problems)
    events = catalog.get("game_events", {}).get("events", [])
    for e in events:
        _check_terms(f"game event {e['id']}", e["requires"], [], catalog, problems)
        _check_terms(f"game event {e['id']}", e["effects"], [], catalog, problems, effect=True)
    # Every story value other than the start must be set by something.
    written: dict[str, set] = {}
    for a in catalog["actions"] + catalog["signals"] + events:
        terms = a.get("effects", []) + a.get("on_complete", []) + a.get("on_fail", [])
        terms += [t for br in a.get("effects_if", []) for t in br["effects"]]
        for t in terms:
            if "world" in t:
                vals = a.get("choices", []) if t["set"] == "$choice" else [t["set"]]
                written.setdefault(t["world"], set()).update(vals)
    for w, vals in catalog["world"]["states"].items():
        got = written.get(w, set())
        unset = [v for v in vals if v != catalog["world"]["start"][w] and v not in got]
        if unset:
            problems.append(f"story state {w}: nothing ever sets {unset}")
    return problems


def check_content(catalog: dict) -> list[str]:
    """data/content.json agrees with the catalog and rooms."""
    problems = []
    content = json.loads((DATA / "content.json").read_text(encoding="utf-8"))
    m = content["machine"]
    signals = {s["id"]: s for s in catalog["signals"]}
    if signals["highlight_file"]["choices"] != [f["id"] for f in m["files"]]:
        problems.append("content: highlight_file choices differ from the file list")
    if signals["play_fragment"]["choices"] != [f["id"] for f in m["fragments"]]:
        problems.append("content: play_fragment choices differ from the fragments")
    clip = {p for ps_ in m["recording_phrases"].values() for p in ps_}
    if not set(m["damaged_segment"]["phrases"]) <= clip:
        problems.append("content: the damaged segment repeats words that are not in the family clip")
    rooms = sorted(p.stem for p in (DATA / "rooms").glob("*.json"))
    if sorted(content["rooms"]) != rooms:
        problems.append(f"content: rooms {sorted(content['rooms'])} differ from data/rooms {rooms}")
    for name, r in content["rooms"].items():
        if r["incomplete_stream"] not in ("anchor", "echo", "none"):
            problems.append(f"content {name}: incomplete_stream must be anchor, echo or none")
    return problems


def check_all(props: dict) -> dict[str, list[str]]:
    catalog = load_catalog()
    out = {"catalog": check_catalog(catalog) + check_content(catalog)}
    for name in build_rooms.ROOMS:
        out[name] = check_room(load_room(name), catalog, props)
    return out


# ------------------------------------------------------------------ drawing


def compose_scene(colours, name: str, room_img: Image.Image, props: dict) -> tuple[Image.Image, dict]:
    """Room background with every object and visible item drawn from the data."""
    catalog = load_catalog()
    room = load_room(name)
    # Contact shadows on the floor under everything standing on it.
    shadow = np.zeros((ps.ROOM_SIZE[1], ps.ROOM_SIZE[0]), bool)
    for o in room["objects"]:
        if catalog["kinds"][o["kind"]]["sprites"] and o["base"] >= 184:
            x0, _, x1, _ = bounds(o, catalog, props)
            shadow[o["base"] - 1: o["base"] + 2, x0 + 1: x1] = True
            shadow[o["base"] + 2, x0 + 3: x1 - 2] = True
    room_img = build_rooms.shade(room_img, colours, shadow & build_rooms.FLOOR, -1)
    scene = room_img.convert("RGBA")
    for o in room["objects"]:
        sprite = sprite_for(o, catalog)
        if not sprite:
            continue
        x0, y0, _, _ = bounds(o, catalog, props)
        scene.alpha_composite(props[sprite], (x0, y0))
        for ov in overlays_for(o, catalog):
            scene.alpha_composite(props[ov["sprite"]], (x0 + ov["dx"], y0 + ov["dy"]))
    for it in room["items"]:
        pos = item_position(it, room, catalog, props)
        if pos:
            scene.alpha_composite(props[catalog["items"][it["kind"]]["sprite"]], pos)
    return scene, room


def main() -> None:
    import build_props
    props = build_props.build_props(ps.load_palette())
    results = check_all(props)
    bad = {k: v for k, v in results.items() if v}
    for k, v in bad.items():
        for p in v:
            print(f"{k}: {p}")
    print(f"room data: {sum(map(len, results.values()))} problems")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
