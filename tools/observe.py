"""What Marycel perceives: turns data/content.json and the live room state into
the text of each observation, and decides whether she notices a signal.

Used by tools/sim.py. Observations never name a source as Elena or the Echo;
the author log in sim.py keeps the true source separately.
"""

from __future__ import annotations

import json

import room_data

CONTENT = json.loads((room_data.DATA / "content.json").read_text(encoding="utf-8"))
APP_NAMES = {"files": "The file list", "video": "The video player", "notes": "NOTES.TXT", "log": "RECOVERY.LOG",
             "diagnostics": "Diagnostics", "recovery": "The recovery tool", "map": "The recovery map"}
SCREEN_WORDS = {"agreed": "YES", "declined": "NO", "warned": "DANGER", "more_tests": "MORE TESTS"}


def _label(w, obj_id):
    return w.catalog["kinds"][w.kind_of(obj_id)]["label"]


def _item_label(w, item):
    return w.catalog["items"][item["kind"]]["label"]


def audible_route(w):
    """Where sound goes now: plugged headphones win, then working speakers."""
    hp = w.item_by_kind("headphones")
    if hp and hp["state"].get("plugged") == "yes":
        return "headphones"
    sp = w.device("speakers")
    if sp and sp["state"].get("connected") == "yes" and sp["state"].get("muted") == "no":
        return "speakers"
    return None


def marycel_x(w):
    if w.marycel["seated"] == "yes":
        return w.objects["computer"].get("sit_x", w.objects["computer"]["stand_x"])
    return w.objects[w.marycel["at"]].get("stand_x", 0)


def facing(w, obj_id):
    """She faces an object she is at, or one on the side her current spot faces."""
    if w.marycel["at"] == obj_id:
        return True
    here = w.objects[w.marycel["at"]]
    there = w.objects[obj_id].get("stand_x", 0)
    side = here.get("facing", "left")
    return there < marycel_x(w) if side == "left" else there > marycel_x(w)


def perceives_now(w, alternatives, device_id):
    """True if any perceived_if alternative holds at this moment. 'doing'
    alternatives are met later, when she reads the screen or the printout."""
    if w.marycel["location"] != "at_object":
        return False
    for alt in alternatives:
        ok = True
        for k, v in alt.items():
            if k == "marycel_within":
                ok &= abs(marycel_x(w) - w.objects[device_id].get("stand_x", 0)) <= v
            elif k == "facing_device":
                ok &= facing(w, device_id) == v
            elif k == "doing":
                ok = False
            elif k == "in_room":
                ok &= v is True
            elif k == "route":
                ok &= audible_route(w) == v
            elif k == "item_state":
                item, st = v.split(".")
                i = w.item_by_kind(item)
                ok &= i is not None and i["state"].get(st) == alt["is"]
            elif k in ("is", "holding"):
                pass
            else:
                raise ValueError(f"unknown perceived_if key {k}")
        if ok:
            return True
    return False


def sound_text(route, what):
    return f"From the {route}: {what}"


def file_text(w, app):
    m = CONTENT["machine"]
    return {"notes": m["notes"], "log": m["recovery_log"], "map": m["streams"]}.get(app, "")


def describe(w, channel, target, params) -> str:
    """The observation text for an action's 'observes' channel."""
    m, room = CONTENT["machine"], CONTENT["rooms"][w.room["id"]]
    if channel == "target_states":
        if target in (None, "floor"):
            return "Nothing special."
        st = w.objects[target]["state"]
        bits = [f"{k} {v}" for k, v in st.items()]
        here = [_item_label(w, i) for i in w.items_at(target)]
        if w.catalog["kinds"][w.kind_of(target)].get("container") and st.get("open") == "no":
            here = []
        return f"{_label(w, target)}: " + (", ".join(bits) or "nothing to adjust") + (
            f". On or in it: {', '.join(here)}." if here else ".")
    if channel == "outside":
        return room["outside"]
    if channel == "ofrenda":
        lit = w.device("ofrenda")["state"].get("candles")
        return f"Candles {lit}. " + room["ofrenda"]
    if channel == "connections":
        return connections(w, target)
    if channel == "device_status":
        return device_status(w)
    if channel == "audio_route":
        r = audible_route(w)
        return f"Test sound: it plays through the {r}." if r else "Test sound: nothing. No speakers or headphones are working."
    if channel == "display":
        return display(w)
    if channel == "recording":
        return m["tape"] if params.get("_source") == "tape" else m["video"][w.video_pos]
    if channel == "file_list":
        return "FILES\n" + "\n".join(f["line"] for f in m["files"])
    if channel == "notes":
        return m["notes"]
    if channel == "recovery_log":
        return m["recovery_log"]
    if channel == "damaged_segment":
        return m["damaged_segment"]["text"]
    if channel == "recovery_status":
        rs = m["recovery_status"]
        return "\n".join([rs["header"], rs["recovery"][w.world["recovery"]], rs["isolation"][w.world["isolation"]], rs["footer"]])
    if channel == "copy_result":
        return m["copy_result"][w.world["video_copy"]]
    if channel == "streams":
        return m["streams"]
    if channel == "stream_history":
        return stream_history(w)
    if channel == "contents":
        box = w.objects[target]
        inside = [_item_label(w, i) for i in w.items_at(target)]
        if box["state"].get("open") == "no":
            return "The box is closed."
        return "In the box: " + (", ".join(inside) if inside else "nothing") + "."
    if channel == "held_item":
        return held_item(w)
    if channel == "held_item_detail":
        h = w.held()
        spec = CONTENT["items"].get(h["kind"]) if h else None
        return spec["back"] if spec and "back" in spec else "Nothing more to see up close."
    if channel == "photo_and_recording":
        return m["photo_and_recording"]
    if channel == "cable_condition":
        return room["cable_condition"]
    raise ValueError(f"no description for channel {channel}")


def connections(w, target):
    kind = w.kind_of(target)
    st = w.objects[target]["state"]
    if kind == "printer":
        return f"Printer cable {st['cable']}; power {st['power']}."
    if kind == "speakers":
        return f"Speakers {'plugged in' if st.get('connected') == 'yes' else 'unplugged'}."
    bits = []
    sp = w.device("speakers")
    if sp:
        bits.append(f"speakers {'plugged in' if sp['state'].get('connected') == 'yes' else 'unplugged'}")
    hp = w.item_by_kind("headphones")
    if hp:
        bits.append(f"headphones {'plugged in' if hp['state'].get('plugged') == 'yes' else 'unplugged'}")
    pr = w.device("printer")
    if pr:
        bits.append(f"printer cable {pr['state']['cable']}")
    bits.append(f"transfer device {'connected' if st.get('device') == 'connected' else 'not connected'}")
    return "Computer: " + "; ".join(bits) + "."


def device_status(w):
    pr = w.device("printer")["state"]
    printer_ok = pr["power"] == "on" and pr["cable"] == "connected" and pr["paper"] == "loaded" and pr["jam"] == "no"
    problems = [p for p, bad in [("off", pr["power"] != "on"), ("unplugged", pr["cable"] != "connected"),
                                 ("no paper", pr["paper"] != "loaded"), ("jammed", pr["jam"] == "yes")] if bad]
    route = audible_route(w)
    return ("DIAGNOSTICS\nscreen: working\n"
            f"sound: {route or 'no working output'}\n"
            f"printer: {'ready' if printer_ok else 'not ready (' + ', '.join(problems) + ')'}")


def display(w):
    st = w.objects["computer"]["state"]
    if st["power"] != "on":
        return "The screen is dark."
    if st["display"] == "app" and st["app"] != "none":
        base = f"{APP_NAMES[st['app']]} is open."
    else:
        base = "The desktop is open."
    if st.get("app") in ("notes", "log", "map"):
        base += "\n" + file_text(w, st["app"])
    if w.screen:
        base += f"\nOn the screen: \"{w.screen['text']}\""
    return base


def held_item(w):
    h = w.held()
    if not h:
        return "Her hands are empty."
    if h["kind"] == "printout":
        c = h.get("content") or {"source": "file", "file": "a blank page", "text": ""}
        spec = CONTENT["items"]["printout"]
        return spec["elena"].format(**c) if c["source"] == "elena" else spec["file"].format(**c)
    if h["kind"] == "notebook":
        return CONTENT["rooms"][w.room["id"]]["notebook"]
    spec = CONTENT["items"].get(h["kind"])
    return spec["front"] if spec else f"The {_item_label(w, h)}."


def stream_history(w):
    m = CONTENT["machine"]["stream_history"]
    out = ["STREAM HISTORY"]
    hidden = w.room["hidden"]["elena_stream"]
    gap = CONTENT["rooms"][w.room["id"]]["incomplete_stream"]
    for s, name in (("stream_a", "A"), ("stream_b", "B")):
        role = "anchor" if s == hidden else "echo"
        source = "elena" if role == "anchor" else "echo"
        line = m["incomplete"] if gap == role else m[role]
        used = w.outputs[source]
        routes = ", ".join(f"{r} x{n}" for r, n in sorted(used.items())) or "none"
        out.append(f"stream {name}: {line} Outputs this session: {routes}.")
    return "\n".join(out)
