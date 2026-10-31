"""Reference rules engine for the room data: applies Marycel's actions and
Elena's signals exactly as data/catalog.json describes them.

The game engine should behave the same way; training-data generation can use
this to produce only valid steps. Running it plays one complete route per room
(prepare the printer, copy the video, contain the passage, ask Elena, transfer)
and fails loudly if any step is refused.

    .venv/Scripts/python tools/sim.py
"""

from __future__ import annotations

import copy

import observe
import room_data


class Refused(Exception):
    def __init__(self, msg, failed=None):
        super().__init__(msg)
        self.failed = failed or []  # the unmet conditions, for plain-language feedback


class World:
    def __init__(self, room_name: str):
        self.catalog = room_data.load_catalog()
        self.room = room_data.load_room(room_name)
        self.actions = {a["id"]: a for a in self.catalog["actions"]}
        self.signals = {s["id"]: s for s in self.catalog["signals"]}
        self.objects = {o["id"]: copy.deepcopy(o) for o in self.room["objects"]}
        for o in self.objects.values():
            o.setdefault("state", {})
        self.items = {i["id"]: copy.deepcopy(i) for i in self.room["items"]}
        for i in self.items.values():
            i.setdefault("state", {})
        self.world = dict(self.catalog["world"]["start"])
        self.marycel = {"location": "at_object", "seated": "no", "holding": None,
                        "at": self.room["marycel_start"]["at"]}
        self.done_actions: set[str] = set()
        self.running: dict[str, tuple] = {}  # long actions still in progress: id -> (rule, target, params)
        self.created: dict[str, int] = {}
        self.log: list[str] = []
        # Perception and content (tools/observe.py, data/content.json).
        self.screen: dict | None = None          # text Elena or the Echo put on screen, until replaced
        self.video_pos = "start"
        self.exposed = {"recording": set(), "damaged": set()}  # phrases the Echo may reuse
        self.outputs = {"elena": {}, "echo": {}}  # route -> count, shown in the stream history
        self.perceived: list[dict] = []           # what Marycel observed or noticed, in order
        self.author_log: list[dict] = []          # every output with its true source (author view only)

    # ------------------------------------------------------------ helpers

    def kind_of(self, obj_id):
        return self.objects[obj_id]["kind"]

    def device(self, kind):
        return next((o for o in self.objects.values() if o["kind"] == kind), None)

    def item_by_kind(self, kind):
        return next((i for i in self.items.values() if i["kind"] == kind), None)

    def held(self):
        h = self.marycel["holding"]
        return self.items[h] if h else None

    @staticmethod
    def _match(value, t):
        if "is" in t:
            allowed = t["is"] if isinstance(t["is"], list) else [t["is"]]
            return value in allowed
        return value not in t["not"]

    def items_at(self, obj_id):
        return [i for i in self.items.values() if i.get("in") == obj_id or (i.get("on") or [None])[0] == obj_id]

    def unlocked(self, name):
        rule = self.catalog["unlocks"][name]["rule"]
        if rule == "always":
            return True
        if "after_any" in rule:
            return bool(self.done_actions & set(rule["after_any"]))
        return self.cond(rule, None)

    # ------------------------------------------------------------ conditions

    def cond(self, t, target, params=None) -> bool:
        if "any" in t:
            return any(all(self.cond(x, target, params) for x in branch) for branch in t["any"])
        if "device" in t:
            d = self.device(t["device"])
            return d is not None and self._match(d["state"].get(t["state"]), t)
        if "state" in t:
            return self._match(self.objects[target]["state"].get(t["state"]), t)
        if "world" in t:
            return self._match(self.world[t["world"]], t)
        if "marycel" in t:
            return self._match(self.marycel[t["marycel"]], t)
        if "holding" in t:
            h, want = self.held(), t["holding"]
            if want is None:
                return h is None
            if want == "*":
                return h is not None
            if want == "readable":
                return h is not None and self.catalog["items"][h["kind"]].get("readable", False)
            return h is not None and h["kind"] == want
        if "item_in_target" in t:
            if params and params.get("item"):
                i = self.items.get(params["item"])
                return i is not None and (i.get("in") == target or (i.get("on") or [None])[0] == target
                                          or (target == "floor" and "floor_x" in i))
            return bool(self.items_at(target))
        if "item_state" in t:
            item, st = t["item_state"].split(".")
            i = self.item_by_kind(item)
            return i is not None and self._match(i["state"].get(st), t)
        if "free_slot" in t:
            slots = self.catalog["kinds"][self.kind_of(target)].get("slots", {})
            used = {tuple(i["on"]) for i in self.items.values() if i.get("on")}
            want = (params or {}).get("slot")
            return (target, want) not in used if want else any((target, s) not in used for s in slots)
        if "unlocked" in t:
            return self.unlocked(t["unlocked"])
        raise ValueError(f"unknown condition {t}")

    # ------------------------------------------------------------ effects

    def effect(self, t, target, params):
        if "device" in t:
            self.device(t["device"])["state"][t["state"]] = t["set"]
        elif "state" in t:
            st = self.objects[target]["state"]
            if t["set"] in ("+1", "-1"):
                values = self.catalog["kinds"][self.kind_of(target)]["states"][t["state"]]
                i = values.index(st[t["state"]]) + (1 if t["set"] == "+1" else -1)
                st[t["state"]] = values[max(0, min(i, len(values) - 1))]
            else:
                st[t["state"]] = t["set"]
        elif "world" in t:
            self.world[t["world"]] = params["choice"] if t["set"] == "$choice" else t["set"]
        elif "marycel" in t:
            self.marycel[t["marycel"]] = t["set"]
        elif "item_state" in t:
            item, st = t["item_state"].split(".")
            self.item_by_kind(item)["state"][st] = t["set"]
        elif "take" in t:
            item = (self.item_by_kind(t["take"]) if t["take"] != "*" else self.items[params["item"]])
            for k in ("in", "on", "floor_x", "at", "worn"):
                item.pop(k, None)
            self.marycel["holding"] = item["id"]
        elif "put_held" in t:
            item = self.held()
            kind = self.kind_of(target) if target in self.objects else target
            spec = self.catalog["kinds"].get(kind, {})
            if spec.get("container"):
                item["in"] = target
            elif spec.get("slots"):
                item["on"] = [target, params["slot"]]
            elif target == "floor":
                item["floor_x"] = self.objects[self.marycel["at"]].get("stand_x", 0)
            else:
                item["at"] = target  # inserted into a device (tape, disk, transfer device)
            self.marycel["holding"] = None
        elif "move_held_to" in t:
            self.held()[t["move_held_to"]] = True
            self.marycel["holding"] = None
        elif "consume_held" in t:
            del self.items[self.marycel["holding"]]
            self.marycel["holding"] = None
        elif "create_held" in t:
            kind = t["create_held"]
            n = self.created[kind] = self.created.get(kind, 0) + 1
            iid = kind if n == 1 else f"{kind}_{n}"
            self.items[iid] = {"id": iid, "kind": kind, "state": {}}
            if kind == "printout":
                self.items[iid]["content"] = self.device("printer").pop("content", None)
            self.marycel["holding"] = iid
        else:
            raise ValueError(f"unknown effect {t}")

    # ------------------------------------------------------------ running

    def _run(self, rule, target, params, who, wait=True):
        reqs = list(rule["requires"])
        if target in self.objects:
            reqs += rule.get("requires_by_kind", {}).get(self.kind_of(target), [])
        failed = [t for t in reqs if not self.cond(t, target, params)]
        if failed:
            raise Refused(f"{who} {rule['id']} on {target}: needs {failed}", failed)
        branches = [b for b in rule.get("effects_if", []) if all(self.cond(t, target, params) for t in b["when"])]
        for t in rule["effects"]:
            self.effect(t, target, params)
        for b in branches:
            for t in b["effects"]:
                self.effect(t, target, params)
        # A running long action fails if this one interrupts it, or ends cleanly if this one ends it.
        for rid, (r, rt, rp) in list(self.running.items()):
            if rule["id"] in r.get("interrupted_by", []):
                for t in r.get("on_fail", []):
                    self.effect(t, rt, rp)
                del self.running[rid]
            elif rule["id"] in r.get("ended_by", []):
                del self.running[rid]
        if "on_complete" in rule:
            self.running[rule["id"]] = (rule, target, params)
            if wait:
                self.finish(rule["id"])

    def finish(self, action_id=None):
        """Let one long action (or all of them) run to the end uninterrupted."""
        for rid in [action_id] if action_id else list(self.running):
            r, rt, rp = self.running.pop(rid)
            for t in r["on_complete"]:
                self.effect(t, rt, rp)

    def _check_params(self, a, target, params):
        """Refuse a step whose fields don't fit the action, as the game will."""
        kinds, spec = a["kinds"], a.get("params", {})
        if kinds == []:
            if target is not None:
                raise Refused(f"{a['id']} takes no target")
        elif target is None:
            raise Refused(f"{a['id']} needs a target")
        elif target == "floor":
            if kinds == "*" or "floor" not in kinds:
                raise Refused(f"{a['id']} cannot target floor")
        elif target not in self.objects:
            raise Refused(f"{a['id']}: no object {target!r} in this room")
        elif kinds != "*" and self.kind_of(target) not in kinds:
            raise Refused(f"{a['id']} cannot target {target}")
        extra = set(params) - set(spec)
        if extra:
            raise Refused(f"{a['id']} does not take {sorted(extra)}")
        if "item" in spec and params.get("item") not in self.items:
            raise Refused(f"{a['id']} needs an item id that exists, got {params.get('item')!r}")
        if "slot" in spec:
            slots = self.catalog["kinds"].get(self.kind_of(target) if target in self.objects else "", {}).get("slots")
            if slots and params.get("slot") not in slots:
                raise Refused(f"{a['id']} on {target} needs a slot from {list(slots)}")
            if not slots and "slot" in params:
                raise Refused(f"{a['id']} on {target} takes no slot")
        for key in ("choice", "position"):
            if key in spec and params.get(key) not in spec[key]:
                raise Refused(f"{a['id']} needs {key} from {spec[key]}, got {params.get(key)!r}")
        if "text" in spec and not params.get("text"):
            raise Refused(f"{a['id']} needs text")

    def act(self, action_id, target=None, wait=True, **params):
        """Run one Marycel step. wait=False leaves a long action running (see finish)."""
        a = self.actions[action_id]
        self._check_params(a, target, params)
        if self.marycel["location"] == "away" and action_id != "return":
            raise Refused(f"{action_id}: she is away; only return is possible")
        before = copy.deepcopy(self.marycel)
        # Using anything other than the computer area stands her up first.
        if (self.marycel["seated"] == "yes" and a["anim"] != "sit_type" and target in self.objects
                and self.kind_of(target) not in ("computer", "chair", "desk", "keyboard")):
            self.marycel["seated"] = "no"
        try:
            self._run(a, target, params, "Marycel", wait)
        except Refused:
            self.marycel = before
            raise
        if target in self.objects:
            self.marycel["at"] = target
        if a["anim"] == "sit_type":
            self.marycel["seated"] = "yes"
        self.done_actions.add(action_id)
        self.log.append(f"{action_id} {target or ''} {params or ''}".strip())
        return self._content_after(a, target, params)

    def _content_after(self, a, target, params):
        """Content side of an action: what it exposes, prints or clears, and what she observes."""
        m = observe.CONTENT["machine"]
        aid, extra = a["id"], {}
        if aid == "play_tape":
            extra["_source"] = "tape"
            self.exposed["recording"].update(m["recording_phrases"]["start"] + m["recording_phrases"]["middle"])
        elif aid == "seek_video":
            self.video_pos = params["position"]
        if aid in ("play_video_file", "seek_video"):
            self.exposed["recording"].update(m["recording_phrases"][self.video_pos])
        elif aid == "open_damaged_segment":
            self.exposed["damaged"].update(m["damaged_segment"]["phrases"])
        elif aid == "print_file":
            app = self.objects["computer"]["state"]["app"]
            name = {"notes": "NOTES.TXT", "log": "RECOVERY.LOG", "map": "WORKSPACE.MAP"}[app]
            self.device("printer")["content"] = {"source": "file", "file": name, "text": observe.file_text(self, app)}
        # Using the computer for anything else replaces what was on screen.
        if (target == "computer" and aid != "read_screen") or self.objects["computer"]["state"]["power"] != "on":
            self.screen = None
        if not a.get("observes"):
            return None
        text = observe.describe(self, a["observes"], target, {**params, **extra})
        self.perceived.append({"step": len(self.log), "from": aid, "text": text})
        return text

    def signal(self, signal_id, **params):
        """Elena acts. Returns True if Marycel notices it at once (screen text and
        printouts can also be found later)."""
        s = self.signals[signal_id]
        if not self.unlocked(s["unlock"]):
            raise Refused(f"signal {signal_id} is still locked")
        if set(params) - set(s["params"]):
            raise Refused(f"signal {signal_id} does not take {sorted(set(params) - set(s['params']))}")
        if s.get("choices") and params.get("choice") not in s["choices"]:
            raise Refused(f"signal {signal_id} needs choice from {s['choices']}, got {params.get('choice')!r}")
        if "text" in s["params"] and not 0 < len(params.get("text", "")) <= s["max_chars"]:
            raise Refused(f"signal {signal_id} needs text of 1 to {s['max_chars']} characters")
        target = self.device(s["device"])["id"]
        self._run(s, target, params, "Elena")
        self.log.append(f"Elena: {signal_id} {params or ''}".strip())
        return self._output("elena", signal_id, s["device"], s["perceived_if"], params)

    def _output(self, source, event_id, device, perceived_if, params):
        """Put an output into the room and decide whether Marycel notices it now."""
        m = observe.CONTENT["machine"]
        route, text = None, None
        if device == "computer" and event_id != "stay_silent":
            route = "screen"
            if "text" in params:
                shown = params["text"]
            elif event_id == "request_pause":
                shown = "PAUSE"
            elif event_id == "transfer_response":
                shown = observe.SCREEN_WORDS[params["choice"]]
            elif event_id == "highlight_file":
                shown = next(f["name"] for f in m["files"] if f["id"] == params["choice"]) + " (highlighted)"
            else:
                shown = params["phrase"].upper()
            self.screen = {"text": shown, "source": source}
            text = f"On the screen: \"{shown}\""
        elif device == "speakers" or event_id == "echo_repeat_phrase":
            route = observe.audible_route(self)
            if event_id == "play_fragment":
                frag = next(f for f in m["fragments"] if f["id"] == params["choice"])
                self.exposed["recording"].update(frag["phrases"])
                what = frag["text"]
            elif event_id == "tone":
                what = "a short, clear tone."
            else:
                what = f"a quiet voice: \"{params['phrase']}\""
            text = observe.sound_text(route, what) if route else None
        elif device == "printer":
            route = "printer"
            self.device("printer")["content"] = {"source": "elena", "text": params["text"]}
        if route:
            self.outputs[source][route] = self.outputs[source].get(route, 0) + 1
        noticed = bool(text) and observe.perceives_now(self, perceived_if, self.device(device)["id"]
                                                      if self.device(device) else "computer")
        if noticed:
            self.perceived.append({"step": len(self.log), "from": "room", "text": text})
        self.author_log.append({"source": source, "event": event_id, "route": route, "params": params,
                                "noticed": noticed})
        return noticed

    def echo(self, event_id, phrase):
        """The Echo acts (game-driven, never the model or the player). It can only
        reuse phrases Marycel has exposed."""
        e = next(e for e in self.catalog["echo"]["events"] if e["id"] == event_id)
        failed = [t for t in e["requires"] if not self.cond(t, None)]
        if failed:
            raise Refused(f"Echo {event_id}: needs {failed}")
        pool = (self.exposed["damaged"] if event_id == "echo_repeat_phrase"
                else self.exposed["damaged"] | self.exposed["recording"])
        if phrase not in pool:
            raise Refused(f"Echo {event_id}: {phrase!r} is not in exposed material {sorted(pool)}")
        like = "tone" if event_id == "echo_repeat_phrase" else "screen_message"
        device = "speakers" if like == "tone" else "computer"
        self.log.append(f"Game: {event_id} {phrase!r}")
        return self._output("echo", event_id, device, self.signals[like]["perceived_if"], {"phrase": phrase})

    def game_event(self, event_id):
        """A game-driven change nobody chooses (catalog game_events), e.g. silence becoming no_answer."""
        e = next(e for e in self.catalog["game_events"]["events"] if e["id"] == event_id)
        self._run(e, None, {}, "Game")
        self.log.append(f"Game: {event_id}")


# ---------------------------------------------------------------- routes


def prepare_printer(w: World):
    room = w.room["id"]
    if room == "repair-shop":
        w.act("open", "storage")
        w.act("take", "storage", item="paper")
        w.act("load_paper", "printer")
        w.act("take", "workbench", item="cable")
        w.act("connect_cable", "printer")
        w.act("switch_on", "printer")
    elif room == "electronics-workshop":
        w.act("take", "workbench", item="paper")
        w.act("load_paper", "printer")
    else:
        w.act("switch_on", "printer")
        w.act("clear_jam", "printer")


def full_route(name: str) -> World:
    w = World(name)
    w.signal("screen_message", text="HELLO MARY")
    w.act("read_screen", "computer")
    prepare_printer(w)
    w.act("enable_printing", "computer")
    w.signal("print_message", text="Copy the video first. Then we talk.")
    w.act("collect_printout", "printer")
    w.act("read_held")
    w.act("put", "floor")
    # Fetch the recording and the archive disk.
    box = w.objects["storage"]
    if box["state"]["open"] == "no":
        w.act("open", "storage")
    w.act("take", "storage", item="recording")
    w.act("insert_recording", "computer")
    w.act("play_tape", "computer")
    w.act("stop_tape", "computer")
    w.act("take", "storage", item="archive_disk")
    w.act("insert_disk", "computer")
    w.act("open_recovery", "computer")
    w.act("copy_playable_video", "computer")
    w.act("verify_copy", "computer")
    w.act("isolate_output", "computer")
    # Transfer device, then the recovery map and Elena's consent.
    dev = w.item_by_kind("transfer_device")
    host = dev.get("in") or dev["on"][0]
    w.act("take", host, item=dev["id"])
    w.act("connect_device", "computer")
    w.act("open_map", "computer")
    w.act("compare_streams", "computer")
    w.act("select_stream", "computer", choice=w.room["hidden"]["elena_stream"])
    w.act("ask_before_transfer", "computer", text="Is this you?")
    w.signal("transfer_response", choice="agreed")
    w.act("start_transfer", "computer")
    return w


def negative_checks() -> list[str]:
    """Things the rules must refuse."""
    out = []
    def ready_to_transfer(w):
        w.act("take", "workbench", item="transfer_device")
        w.act("connect_device", "computer")
        w.act("open_recovery", "computer")
        w.act("isolate_output", "computer")
        w.act("open_map", "computer")
        w.act("select_stream", "computer", choice="stream_a")

    # (label, setup that must succeed, final step that must be refused, word the refusal must mention)
    cases = [
        ("transfer before asking Elena", ready_to_transfer, lambda w: w.act("start_transfer", "computer"), "transfer_consent"),
        ("take from a closed box", lambda w: None, lambda w: w.act("take", "storage", item="recording"), "open"),
        ("preview the damaged segment after containment",
         lambda w: (w.act("open_recovery", "computer"), w.act("isolate_output", "computer"), w.act("open_video_file", "computer")),
         lambda w: w.act("open_damaged_segment", "computer"), "passage"),
        ("Elena answers before Marycel asks", ready_to_transfer,
         lambda w: w.signal("transfer_response", choice="agreed"), "transfer_consent"),
        ("Elena answers with an unknown choice",
         lambda w: (ready_to_transfer(w), w.act("ask_before_transfer", "computer", text="Is this you?")),
         lambda w: w.signal("transfer_response", choice="banana"), "choice"),
        ("take without naming the item", lambda w: None, lambda w: w.act("take", "workbench"), "item"),
        ("put into a slot that does not exist", lambda w: w.act("take", "workbench", item="cable"),
         lambda w: w.act("put", "workbench", slot="roof"), "slot"),
        ("walk to an object that is not in the room", lambda w: None, lambda w: w.act("walk_to", "banana"), "no object"),
        ("say aloud at an object", lambda w: None, lambda w: w.act("say_aloud", "computer", text="hi"), "no target"),
        ("select a stream that does not exist", lambda w: (w.act("open_recovery", "computer"), w.act("open_map", "computer")),
         lambda w: w.act("select_stream", "computer", choice="stream_z"), "choice"),
        ("use the computer while away", lambda w: w.act("leave_room", "door"),
         lambda w: w.act("open_notes", "computer"), "away"),
        ("print a file with the cable unplugged", lambda w: None, lambda w: w.act("print_file", "computer"), "cable"),
    ]
    for label, setup, step, reason in cases:
        w = World("repair-shop")
        setup(w)
        try:
            step(w)
            out.append(f"NOT refused: {label}")
        except Refused as e:
            if reason not in str(e):
                out.append(f"refused for the wrong reason: {label}: {e}")
    return out


def main() -> None:
    problems = []
    for name in ("repair-shop", "electronics-workshop", "home-workshop"):
        try:
            w = full_route(name)
            print(f"{name}: {len(w.log)} steps; video {w.world['video_copy']}, passage {w.world['passage']}, "
                  f"transfer {w.world['transfer']} ({w.world['selected_stream']}, consent {w.world['transfer_consent']})")
        except Refused as e:
            problems.append(f"{name}: {e}")
    problems += negative_checks()
    problems += long_action_checks()
    problems += perception_checks()
    for p in problems:
        print("PROBLEM:", p)
    print(f"simulation: {len(problems)} problems")
    if problems:
        raise SystemExit(1)


def long_action_checks() -> list[str]:
    """Reach the in-progress states: pause, stop and interrupt long actions."""
    out = []

    def expect(w, label, **want):
        got = {k: w.world[k] for k in want}
        if got != want:
            out.append(f"{label}: got {got}, expected {want}")

    # Recovery: run it, pause it, then a shutdown while active makes the passage uncertain.
    w = World("repair-shop")
    w.act("open_recovery", "computer")
    w.act("start_recovery", "computer", wait=False)
    expect(w, "recovery running", recovery="active", passage="active")
    w.act("pause_recovery", "computer")
    expect(w, "recovery paused", recovery="paused", passage="stirring")
    w.act("start_recovery", "computer", wait=False)
    w.act("shut_down", "computer")
    expect(w, "shut down during recovery", recovery="interrupted", passage="uncertain")

    # Copy: interrupted copy fails and can be retried.
    w = World("repair-shop")
    w.act("open", "storage")
    w.act("take", "storage", item="archive_disk")
    w.act("insert_disk", "computer")
    w.act("open_recovery", "computer")
    w.act("copy_playable_video", "computer", wait=False)
    expect(w, "copy running", video_copy="copying")
    w.act("restart", "computer")
    expect(w, "restart during copy", video_copy="failed")
    if w.running:
        out.append(f"restart left long actions running: {list(w.running)}")

    # Transfer: stop it cleanly, retry, then lose power mid-transfer.
    w = World("repair-shop")
    w.act("take", "workbench", item="transfer_device")
    w.act("connect_device", "computer")
    w.act("open_recovery", "computer")
    w.act("isolate_output", "computer")
    w.act("open_map", "computer")
    w.act("select_stream", "computer", choice="stream_a")
    w.act("ask_before_transfer", "computer", text="Is this you?")
    w.game_event("consent_timeout")
    expect(w, "silence", transfer_consent="no_answer")
    try:
        w.act("start_transfer", "computer", wait=False)
        out.append("transfer started without Elena's yes")
    except Refused:
        pass
    w.act("ask_before_transfer", "computer", text="Is this you?")
    w.signal("transfer_response", choice="agreed")
    w.act("start_transfer", "computer", wait=False)
    expect(w, "transfer running", transfer="running", passage="transfer")
    w.act("stop_transfer", "computer")
    expect(w, "transfer stopped", transfer="stopped")
    w.act("start_transfer", "computer", wait=False)
    w.act("shut_down", "computer")
    expect(w, "shut down mid-transfer", transfer="failed", passage="uncertain")
    return out



def perception_checks() -> list[str]:
    """Signals reach Marycel only through working routes; the Echo reuses only
    exposed phrases; observations never name a source."""
    out = []

    def check(ok, label):
        if not ok:
            out.append(label)

    # Repair shop: speakers work, so she hears a tone in the room.
    w = World("repair-shop")
    check(w.signal("tone"), "repair shop: tone through working speakers not noticed")
    # Far from the computer she misses a screen message, then finds it by reading the screen.
    w.act("walk_to", "storage")
    check(not w.signal("screen_message", text="OVER HERE"), "screen message noticed from across the room")
    w.act("read_screen", "computer")
    check("OVER HERE" in w.perceived[-1]["text"], "read_screen did not show the waiting message")
    # The Echo needs the damaged segment opened, then is heard; isolation silences it.
    try:
        w.echo("echo_repeat_phrase", "come see")
        out.append("Echo spoke before the damaged segment was opened")
    except Refused:
        pass
    w.act("open_recovery", "computer")
    w.act("open_files", "computer")
    w.act("open_video_file", "computer")
    w.act("open_damaged_segment", "computer")
    check(w.echo("echo_repeat_phrase", "come see"), "Echo phrase through speakers not noticed")
    try:
        w.echo("echo_repeat_phrase", "one more try")
        out.append("Echo used a phrase that was never exposed")
    except Refused:
        pass
    w.act("open_recovery", "computer")
    w.act("isolate_output", "computer")
    try:
        w.echo("echo_repeat_phrase", "fold it back")
        out.append("Echo spoke through an isolated output")
    except Refused:
        pass
    w.act("open_map", "computer")
    hist = w.act("compare_streams", "computer")
    check("x1" in hist, f"stream history does not show this session's outputs: {hist}")
    for p in w.perceived:
        if any(word in p["text"] for word in ("Echo", "anchor", "elena_stream")):
            out.append(f"an observation names a source: {p['text'][:60]}")

    # Electronics workshop: sound goes to the headphones; heard only once she wears them.
    w = World("electronics-workshop")
    check(not w.signal("tone"), "tone noticed through headphones she is not wearing")
    w.act("take", "workbench", item="headphones")
    w.act("put_on_headphones")
    check(w.signal("tone"), "tone not noticed through worn headphones")

    # Home workshop: no speakers plugged in, so Elena cannot play a tone at all.
    w = World("home-workshop")
    try:
        w.signal("tone")
        out.append("tone allowed with no working output")
    except Refused:
        pass

    # Every observation channel renders in every room.
    for name in ("repair-shop", "electronics-workshop", "home-workshop"):
        w = World(name)
        targets = {"connections": "computer", "contents": "storage", "target_states": "printer"}
        for a in w.catalog["actions"]:
            ch = a.get("observes")
            if ch:
                try:
                    text = observe.describe(w, ch, targets.get(ch, "computer"), {})
                    check(bool(text), f"{name}: empty observation for {ch}")
                except Exception as e:  # noqa: BLE001 - report any rendering failure
                    out.append(f"{name}: observation {ch} failed: {e!r}")
    return out


if __name__ == "__main__":
    main()
