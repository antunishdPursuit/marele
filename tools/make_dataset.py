"""Training data for Marycel's model: plays many randomized episodes through the
rules engine (tools/sim.py) and records each of her steps as one chat example.

Each example is what the game will send the model (a system prompt with the
rules and actions, and a user prompt with what she can see, what she did
recently and what just happened) and the step she took, as one JSON object in
the catalog's action format plus a short "line" she says or thinks.

Every target step was accepted by the rules engine. Elena and the Echo act on
their own schedules; Marycel only learns about a signal if she perceives it.
Some episodes include a refused step (a plausible mistake); the example after it
teaches the fix, never the mistake. Episodes use separate seeds for the
training and held-out evaluation sets.

    .venv/Scripts/python tools/make_dataset.py            # writes data/training/
    .venv/Scripts/python tools/make_dataset.py --check    # replays every example
"""

from __future__ import annotations

import argparse
import copy
import json
import random
from collections import Counter
from pathlib import Path

import observe
import room_data
from sim import Refused, World

ROOMS = ("repair-shop", "electronics-workshop", "home-workshop")
OUT = room_data.DATA / "training"
CATALOG = room_data.load_catalog()
ACTIONS = {a["id"]: a for a in CATALOG["actions"]}
MAX_STEPS = 140


class TooLong(Exception):
    pass


# ---------------------------------------------------------------- prompts

def action_list() -> str:
    lines = []
    for a in CATALOG["actions"]:
        k = a["kinds"]
        tgt = "" if k == [] else (" target:any" if k == "*" else " target:" + "|".join(k))
        ps = []
        for name, v in a.get("params", {}).items():
            if name == "target":
                continue
            ps.append(f"{name}:{'|'.join(v)}" if isinstance(v, list) else name)
        lines.append(f"{a['id']}{tgt}{(' ' + ' '.join(ps)) if ps else ''}")
    return "\n".join(lines)


SYSTEM = f"""You are Marycel, a computer repair technician. You are in your workshop at night with your family's old computer, recovering a family video for the ofrenda. You do not know what is inside the machine. Act only on what you have actually seen, heard or read.

Each turn you get what you can see around you, your recent steps and what just happened. Reply with exactly one JSON object for your next step:
{{"action": "...", "target": "...", ...other fields..., "line": "..."}}
- action: one id from the list below. target: an object id in this room, when the action takes one.
- item (take only), slot (put on the workbench or ofrenda), text (your words), choice, position: only when the action lists them.
- line: one short sentence you say or think. It never changes anything; only actions do.
The game checks every step. A refused step changes nothing; read why and fix it.

Actions:
{action_list()}"""


def _state_text(st):
    return ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in st.items())


def item_label(w, iid):
    return CATALOG["items"][w.items[iid]["kind"]]["label"].lower()


def surroundings(w) -> str:
    """What she can see in the room right now (never story facts or sources)."""
    out = [f"Room: {w.room['label']}. {w.room['situation']}"]
    m = w.marycel
    if m["location"] == "away":
        out.append("You: away from the room (only return works).")
    else:
        held = w.held()
        pose = "sitting at" if m["seated"] == "yes" else "at"
        hp = w.item_by_kind("headphones")
        worn = ", wearing the headphones" if hp and hp.get("worn") else ""
        out.append(f"You: {pose} the {m['at']}, holding {held['id'] if held else 'nothing'}{worn}.")
    out.append("Objects:")
    for oid, o in w.objects.items():
        label = CATALOG["kinds"][o["kind"]]["label"].lower()
        out.append(f"- {oid} ({label})" + (f": {_state_text(o['state'])}" if o["state"] else ""))
    seen = []
    for iid, i in w.items.items():
        if iid == m["holding"] or i.get("worn"):
            continue
        if i.get("in"):
            if w.objects[i["in"]]["state"].get("open") == "no":
                continue
            seen.append(f"{iid} in the {i['in']}")
        elif i.get("on"):
            seen.append(f"{iid} on the {i['on'][0]} ({i['on'][1]})")
        elif "floor_x" in i:
            seen.append(f"{iid} on the floor")
        elif i.get("at"):
            continue  # inserted into the computer; its state shows it
    out.append("Items you can see: " + (", ".join(seen) if seen else "none") + ".")
    return "\n".join(out)


def step_json(step: dict) -> str:
    return json.dumps(step, ensure_ascii=False)


def user_prompt(w, mem) -> str:
    parts = [surroundings(w)]
    if mem.earlier:
        parts.append("Earlier:\n" + "\n".join(f"- {e}" for e in mem.earlier[-10:]))
    if len(mem.recent) > 1:
        parts.append("Recent steps:\n" + "\n".join(f"> {s}\n  {r}" for s, r in mem.recent[-6:-1]))
    if mem.recent:
        parts.append(f"Your last step:\n> {mem.recent[-1][0]}")
    parts.append("What happened:\n" + ("\n".join(mem.now) if mem.now else "Nothing yet. This is the start."))
    return "\n\n".join(parts)


# ---------------------------------------------------------------- refusals in plain words

WORLD_REASONS = {
    "transfer_consent": {"none": "you haven't asked about the transfer yet",
                         "asked": "there's no answer to your question yet"},
    "selected_stream": {"none": "no stream is selected on the map"},
    "passage": {"*": "the recovery tool won't allow that now"},
    "recovery": {"*": "the recovery tool won't allow that in its current state"},
    "video_copy": {"preserved": "the video is already copied", "copying": "a copy is already running",
                   "*": "there's no copy for that"},
    "isolation": {"*": "the workspace output isn't isolated"},
    "recording_status": {"*": "nothing has played yet"},
}


def explain(e: Refused, w, target) -> str:
    if not e.failed:
        msg = str(e)
        if "away" in msg:
            return "you're away from the room; only return works"
        return "that step doesn't fit this action here"
    reasons = []
    for t in e.failed:
        if "holding" in t:
            want = t["holding"]
            reasons.append("your hands are full" if want is None else
                           "you aren't holding anything" if want == "*" else
                           "you aren't holding anything readable" if want == "readable" else
                           f"you need to be holding the {CATALOG['items'][want]['label'].lower()}")
        elif "device" in t or "state" in t:
            obj = w.device(t["device"]) if "device" in t else w.objects.get(target)
            if obj is None:
                reasons.append(f"there is no {t['device']} here")
                continue
            cur = obj["state"].get(t["state"])
            if t["state"] == "app":
                want = t["is"] if isinstance(t["is"], list) else [t["is"]]
                reasons.append(f"{observe.APP_NAMES[want[0]]} isn't open" if len(want) == 1
                               else "no file is open on the computer")
            else:
                reasons.append(f"the {obj['id']}'s {t['state'].replace('_', ' ')} is {cur}")
        elif "world" in t:
            table = WORLD_REASONS.get(t["world"], {})
            reasons.append(table.get(w.world[t["world"]], table.get("*", "it isn't possible yet")))
        elif "item_in_target" in t:
            reasons.append("that item isn't there")
        elif "free_slot" in t:
            reasons.append("there's no free space there")
        elif "item_state" in t:
            reasons.append(f"the {t['item_state'].split('.')[0]} aren't ready")
        elif "any" in t:
            reasons.append("the tape or the video must be playing")
        elif "marycel" in t:
            reasons.append("you're away from the room" if w.marycel["location"] == "away" else "you're already here")
        else:
            reasons.append("it isn't possible yet")
    return "; ".join(dict.fromkeys(reasons))


# ---------------------------------------------------------------- what she says

LINES = {
    "open": ["Let's see what's in here.", "Opening the box.", "Where did I put everything?"],
    "take": ["I'll grab the {item}.", "The {item}. Got it.", "I need the {item}."],
    "put": ["Setting this down.", "Out of my hands for now.", "Let me put this here."],
    "insert_recording": ["Tape goes in.", "Let's see if the deck still reads it."],
    "play_tape": ["Come on, play.", "Let's hear it.", "Mom used to play this every year."],
    "stop_tape": ["That's enough for now.", "Stopping the tape."],
    "insert_disk": ["Blank archive disk in.", "Disk's in."],
    "open_recovery": ["Let's look at the recovery tool.", "What did this tool leave behind?"],
    "copy_playable_video": ["Copy the good part first. Always.", "Copying what still plays."],
    "verify_copy": ["Did it take?", "Let me check the copy."],
    "isolate_output": ["Cut it off from the speakers.", "Isolating that output.", "Nothing gets out of that workspace."],
    "connect_device": ["Second drive connected.", "Plugging in the new drive."],
    "open_map": ["What's in that workspace?", "Opening the map."],
    "compare_streams": ["Two streams. Which is which?", "Let me compare them."],
    "open_files": ["What's on this old thing?", "Let's see the files."],
    "open_notes": ["Her notes.", "NOTES.TXT. Let's read it."],
    "open_log": ["What happened the last time this ran?", "The recovery log."],
    "run_diagnostics": ["Let me run diagnostics.", "Is everything even working?"],
    "open_video_file": ["Let's open the video file.", "The digital copy."],
    "play_video_file": ["Let's watch it.", "Play."],
    "open_damaged_segment": ["What's in the damaged part?", "Let's see the tail."],
    "look_out": ["Still dark out.", "Quiet night."],
    "visit_ofrenda": ["Hi, Mom. Hi, Dad.", "Almost ready for you."],
    "light_candles": ["There.", "Light for the ofrenda."],
    "read_held": ["Let's read it.", "What does it say?"],
    "write_note": ["Writing it down.", "So I don't forget."],
    "load_paper": ["Paper in.", "Loading paper."],
    "connect_cable": ["Cable in.", "Hooking up the printer."],
    "switch_on": ["Power on.", "Let's wake it up."],
    "clear_jam": ["Something's stuck in here.", "Clearing the jam."],
    "enable_printing": ["Let the computer print.", "Turning on printing."],
    "collect_printout": ["Something printed.", "What came out of the printer?"],
    "test_sound": ["Where does the sound go?", "Testing the sound."],
    "check_connections": ["What's plugged in?", "Let me check the cables."],
    "put_on_headphones": ["Headphones on.", "Let me listen properly."],
    "connect_speakers": ["Speakers back on.", "Plugging the speakers in."],
    "read_screen": ["What's on the screen?", "Let me read that."],
    "inspect": ["Let me look at the {target}.", "Hm. The {target}."],
    "examine_with_magnifier": ["Let me look closer.", "There's something on the back."],
    "compare_photo": ["Is that the same day?", "The photo and the video..."],
    "wait": ["I'll give it a moment.", "Waiting.", "Come on..."],
    "start_transfer": ["Okay. Here we go.", "Starting the transfer."],
    "leave_room": ["I need some air.", "I'll be right back."],
    "return": ["Back.", "Okay. Back to it."],
    "sit_down": ["Let me sit.", "Sitting down."],
    "select_stream": ["That one.", "I'll go with this stream."],
    "ask_before_transfer": ["I should ask first.", "I won't do this without asking."],
    "type_message": ["Let me answer.", "I'll type back."],
    "say_aloud": ["Hello?", ""],
    "test_cable": ["Is this cable any good?", "Testing the cable."],
    "search": ["What's left in the box?", "Let me look through it."],
    "close_program": ["Closing that.", "Done with that window."],
}
REALIZE = ["Oh. Right.", "Right, first things first.", "Okay, that didn't work.", "My mistake.", "Of course."]


def line_for(rng, step, w, prefix=None):
    pool = LINES.get(step["action"], ["Okay."])
    item = item_label(w, step["item"]) if step.get("item") in w.items else ""
    text = rng.choice(pool).format(item=item, target=step.get("target", ""))
    if prefix:
        text = f"{rng.choice(REALIZE)} {text}".strip()
    return text or "..."


# ---------------------------------------------------------------- memory of an episode

class Memory:
    def __init__(self):
        self.earlier: list[str] = []
        self.recent: list[tuple[str, str]] = []
        self.now: list[str] = []

    def record(self, step, result):
        self.recent.append((step_json({k: v for k, v in step.items() if k != "line"}), result.replace("\n", "\n  ")))
        if len(self.recent) > 6:
            s, r = self.recent.pop(0)
            flat = " / ".join(x.strip() for x in r.split("\n") if x.strip())
            self.earlier.append(f"{json.loads(s)['action']}: {flat[:160]}")


# ---------------------------------------------------------------- one episode

ELENA_SCREEN = ["HELLO MARY", "MARY", "IT'S ME", "TIA ELENA", "DON'T RESET", "COPY FIRST", "HELP", "WAIT",
                "FLOWER", "I'M HERE", "PLEASE", "MARY? HI"]
ELENA_NOTES = [
    "Mary, it's Elena. Don't run the recovery again. Copy the video first.",
    "I'm in the workspace. The other voice copies the tape. It isn't me.",
    "It's Tia Elena. The PAUSE in the log was mine. Please be careful.",
    "Mary, the voice on the tail uses our words. Ask me something only I would know.",
]
ELENA_PRINTS = [
    "Copy the video first. Then we talk.",
    "Mary, it's Elena. I paused the recovery that night. Don't start it again.",
    "The other stream learned our words from the tape. I am the one at the PAUSE.",
]
ELENA_ANSWERS = ["FOLD IT BACK", "THE FLOWER", "IT'S ELENA", "YES", "I'M INSIDE", "TORN PETAL"]
MARY_TYPES = ["Who is this?", "Is someone there?", "Hello?", "Who are you?", "What do you want?",
              "Are you okay?", "Can you hear me?"]
MARY_TESTS = ["What did we make for the ofrenda?", "What did you show me with the flower?",
              "What do I call you?", "Where were you that night?"]
MARY_ASKS = ["Is this you? Can I move you to the new drive?", "Should I start the transfer?",
             "I found your stream, I think. Do you want me to move you?", "Are you ready to go?"]
MARY_SAYS = ["Hello?", "Who's there?", "Is someone there?", "Okay. That's not normal.", "I heard that."]
HIGHLIGHT_OPENS = {"notes": "open_notes", "recovery_log": "open_log", "recovery_map": "open_map",
                   "family_video": "open_video_file", "damaged_tail": "open_video_file"}


class Episode:
    def __init__(self, room, seed):
        self.rng = random.Random(seed)
        self.room, self.seed = room, seed
        self.w = World(room)
        self.mem = Memory()
        self.calls: list[list] = []        # replay log: every call, in order
        self.examples: list[dict] = []
        self.p_elena = self.rng.uniform(0.08, 0.3)
        self.p_echo = self.rng.uniform(0.1, 0.4)
        self.p_mistake = self.rng.choice([0.05, 0.15, 0.25])
        self.hasty = self.rng.random() < 0.35
        self.spooked = False
        self.after_refusal = None
        self.asked = 0
        self.reaction: list[dict] = []
        self.last_noticed: list[str] = []

    # ---------------- the world around her

    def _call(self, kind, *args, **kw):
        self.calls.append([kind, list(args), kw])
        w = self.w
        if kind == "signal":
            return w.signal(*args, **kw)
        if kind == "echo":
            return w.echo(*args, **kw)
        if kind == "game":
            return w.game_event(*args)
        raise ValueError(kind)

    def _try(self, kind, *args, **kw):
        trial = copy.deepcopy(self.w)
        try:
            getattr(trial, {"signal": "signal", "echo": "echo"}[kind])(*args, **kw)
        except Refused:
            return None
        return self._call(kind, *args, **kw)

    def others_act(self, step):
        """Elena and the Echo take their turn after each of Marycel's steps."""
        w, rng = self.w, self.rng
        before = len(w.perceived)
        consent = w.world["transfer_consent"]
        if consent == "asked" and step["action"] != "ask_before_transfer" or (
                consent == "asked" and rng.random() < 0.5):
            self.elena_answers_transfer()
        elif step["action"] == "type_message" and rng.random() < 0.75:
            self._try("signal", "answer_typed", text=rng.choice(ELENA_ANSWERS))
        elif rng.random() < self.p_elena:
            self.elena_signal()
        if (w.exposed["damaged"] and w.world["isolation"] == "off" and rng.random() < self.p_echo):
            self._try("echo", "echo_repeat_phrase", rng.choice(sorted(w.exposed["damaged"])))
        return [p["text"] for p in w.perceived[before:] if p["from"] == "room"]

    def elena_signal(self):
        w, rng = self.w, self.rng
        options = [("screen_message", {"text": rng.choice(ELENA_SCREEN)}), ("tone", {})]
        if w.unlocked("file_route"):
            options.append(("highlight_file", {"choice": rng.choice(list(HIGHLIGHT_OPENS))}))
        if w.unlocked("fragments"):
            options.append(("play_fragment", {"choice": rng.choice([f["id"] for f in observe.CONTENT["machine"]["fragments"]])}))
        if w.unlocked("text_channel"):
            options.append(("long_note", {"text": rng.choice(ELENA_NOTES)}))
        if w.unlocked("print_route"):
            options += [("print_message", {"text": rng.choice(ELENA_PRINTS)})] * 2
        sid, params = rng.choice(options)
        self._try("signal", sid, **params)

    def elena_answers_transfer(self):
        w, rng = self.w, self.rng
        right = w.world["selected_stream"] == w.room["hidden"]["elena_stream"]
        if not right:
            choice = "warned" if rng.random() < 0.8 else "declined"
        elif self.asked >= 3:
            choice = "agreed"
        else:
            choice = rng.choices(["agreed", "more_tests", "silent", "declined"], [0.4, 0.3, 0.15, 0.15])[0]
        if choice == "silent":
            return
        self._try("signal", "transfer_response", choice=choice)

    # ---------------- her steps

    def step(self, action, target=None, line=None, **params):
        s = {"action": action}
        if target is not None:
            s["target"] = target
        s.update(params)
        if line is not None:
            s["line"] = line
        return s

    def do(self, s, mistake_ok=True):
        """Record the example, then run the step through the rules."""
        if "line" not in s:
            s["line"] = line_for(self.rng, s, self.w, self.after_refusal)
        prompt = user_prompt(self.w, self.mem)
        self.examples.append({"room": self.room, "seed": self.seed, "replay": copy.deepcopy(self.calls),
                              "prompt": prompt, "target": s, "kind": self.kind_of_example(s)})
        self.after_refusal = None
        params = {k: v for k, v in s.items() if k not in ("action", "target", "line")}
        self.calls.append(["act", [s["action"], s.get("target")], params])
        result = self.w.act(s["action"], s.get("target"), **params)
        if result is None:
            result = f"Done: {ACTIONS[s['action']]['label'].lower()}."
        if s["action"] == "wait" and self.w.world["transfer_consent"] == "asked":
            self._call("game", "consent_timeout")
            result = "You wait. Nothing appears on the screen."
        self.mem.record(s, result)
        noticed = self.others_act(s)
        self.mem.now = [result] + noticed
        self.last_noticed = noticed
        if len(self.examples) > MAX_STEPS:
            raise TooLong()

    def kind_of_example(self, s):
        if s.get("line") == "I'll start with this one.":
            return "hasty"  # kept in the history, never taught
        if self.after_refusal:
            return "fix_after_refusal"
        if self.w.world["transfer_consent"] != "none":
            return "consent"  # every step once she has asked: what she does with the answer
        if self.mem.now and len(self.mem.now) > 1:
            return "reaction"
        if s["action"] in ("start_transfer", "ask_before_transfer", "select_stream", "write_note"):
            return "decision"
        return "routine"

    def mistake(self, wrong):
        """Try a plausible step that the rules refuse; the next example is the fix."""
        trial = copy.deepcopy(self.w)
        params = {k: v for k, v in wrong.items() if k not in ("action", "target", "line")}
        try:
            trial.act(wrong["action"], wrong.get("target"), **params)
            return
        except Refused as e:
            reason = explain(e, self.w, wrong.get("target"))
        if "line" not in wrong:
            wrong["line"] = line_for(self.rng, wrong, self.w)
        self.calls.append(["refused", [wrong["action"], wrong.get("target")], params])
        self.mem.record(wrong, f"REFUSED: {reason}.")
        self.mem.now = [f"REFUSED: {reason}."]
        self.after_refusal = True

    def run(self, s, before=None):
        """One planned step, maybe preceded by trying the step it enables too early."""
        self.react()
        if before is not None and self.rng.random() < self.p_mistake:
            self.mistake(dict(before))
        self.do(s)
        self.react()

    # ---------------- reacting to what she noticed

    def react(self):
        noticed, self.last_noticed = self.last_noticed, []
        if not noticed:
            return
        w, rng = self.w, self.rng
        text = " ".join(noticed)
        screen = "On the screen" in text
        voice = "quiet voice" in text
        sound = text.startswith("From the") or "From the" in text
        if voice:
            self.spooked = True
        if "(highlighted)" in text:
            return  # highlights are seen on read_screen; nothing to react to yet
        if screen and w.objects["computer"]["state"]["power"] == "on" and rng.random() < 0.65:
            reply = rng.choice(MARY_TYPES if w.world["transfer_consent"] in ("none", "asked") else MARY_TESTS)
            self.do(self.step("type_message", "computer", text=reply,
                              line=rng.choice(["Someone's typing.", "Is this a joke?", "Okay. I'll answer.",
                                               "That wasn't me."])))
        elif sound and rng.random() < 0.6:
            if voice:
                self.do(self.step("say_aloud", text=rng.choice(MARY_SAYS),
                                  line=rng.choice(["That voice came from the speakers.", "Those are words from the video.",
                                                   "Nope. Nope."])))
            else:
                self.do(self.step("test_sound", "computer", line=rng.choice(
                    ["Where did that come from?", "Was that the speakers?", "Did something just play?"])))

    # ---------------- helpers for her plan

    def free_slot(self, obj):
        slots = CATALOG["kinds"][self.w.kind_of(obj)].get("slots", {})
        used = {tuple(i["on"]) for i in self.w.items.values() if i.get("on")}
        free = [s for s in slots if (obj, s) not in used]
        return free[0] if free else None

    def put_down(self):
        w = self.w
        if not w.marycel["holding"]:
            return
        slot = self.free_slot("workbench")
        if slot and self.rng.random() < 0.4:
            self.run(self.step("put", "workbench", slot=slot))
        else:
            self.run(self.step("put", "floor"))

    def get(self, iid):
        w = self.w
        if w.marycel["holding"] == iid:
            return True
        item = w.items.get(iid)
        if item is None:
            return False
        host = item.get("in") or (item.get("on") or [None])[0] or ("floor" if "floor_x" in item else None)
        if host is None:
            return False
        take = self.step("take", host, item=iid)
        if w.marycel["holding"]:
            held = w.marycel["holding"]
            if self.rng.random() < 0.5:
                self.mistake(dict(take))
            if w.marycel["holding"] == held:
                self.put_down()
        if host in w.objects and w.objects[host]["state"].get("open") == "no":
            self.run(self.step("open", host), before=take)
        self.run(take)
        return True

    def at_computer(self, action, before=None, **params):
        self.run(self.step(action, "computer", **params), before=before)

    # ---------------- her plan

    def explore(self):
        w, rng = self.w, self.rng
        tasks = ["look_out", "ofrenda", "notebook", "diagnostics", "inspect", "sound", "files"]
        rng.shuffle(tasks)
        for t in tasks[:rng.randint(2, 6)]:
            if t == "look_out":
                self.run(self.step("look_out", "window"))
            elif t == "ofrenda":
                self.run(self.step("visit_ofrenda", "ofrenda"))
                if w.objects["ofrenda"]["state"]["candles"] == "unlit" and rng.random() < 0.6:
                    self.run(self.step("light_candles", "ofrenda"))
            elif t == "notebook":
                if self.get("notebook"):
                    self.run(self.step("read_held"))
                    self.put_down()
            elif t == "diagnostics":
                self.at_computer("run_diagnostics")
            elif t == "inspect":
                self.run(self.step("inspect", rng.choice(["printer", "speakers", "storage", "computer", "workbench"])))
            elif t == "sound":
                self.fix_sound()
            elif t == "files":
                self.at_computer("open_files")
                for f in rng.sample(["open_notes", "open_log"], rng.randint(1, 2)):
                    self.at_computer(f)
            if rng.random() < 0.08 and t != "files":
                self.run(self.step("leave_room", "door"))
                self.away_events()
                self.run(self.step("return", "door"))

    def away_events(self):
        for _ in range(self.rng.randint(0, 2)):
            self.elena_signal()

    def fix_sound(self):
        w = self.w
        self.at_computer("test_sound")
        hp = w.item_by_kind("headphones")
        if hp and hp["state"].get("plugged") == "yes" and hp["state"].get("worn") == "no":
            if self.get(hp["id"]):
                self.run(self.step("put_on_headphones"))
        sp = w.device("speakers")
        if sp and sp["state"]["connected"] == "no" and not hp and self.rng.random() < 0.7:
            self.run(self.step("connect_speakers", "speakers"))
            self.at_computer("test_sound")

    def recording(self):
        w, rng = self.w, self.rng
        if rng.random() < 0.6:
            if self.get("recording"):
                self.at_computer("insert_recording")
                self.at_computer("play_tape")
                if rng.random() < 0.3 and self.get_photo():
                    self.run(self.step("compare_photo", "computer"))
                    self.put_back_photo()
                self.at_computer("stop_tape")
        else:
            self.at_computer("open_video_file")
            self.at_computer("play_video_file")
            if rng.random() < 0.6:
                self.at_computer("seek_video", position="middle")
            if rng.random() < 0.3:
                self.at_computer("seek_video", position="end")

    def get_photo(self):
        return self.get("photo")

    def put_back_photo(self):
        if self.w.marycel["holding"] == "photo" and self.free_slot("ofrenda"):
            self.run(self.step("put", "ofrenda", slot=self.free_slot("ofrenda")))
        else:
            self.put_down()

    def damaged(self):
        w = self.w
        if w.world["passage"] not in ("dormant", "stirring"):
            return
        if w.objects["computer"]["state"]["app"] != "video":
            self.at_computer("open_video_file")
        self.at_computer("open_damaged_segment")

    def printer(self):
        w, rng = self.w, self.rng
        pr = w.device("printer")["state"]
        enable = self.step("enable_printing", "computer")
        if pr["paper"] == "empty" and self.get("paper"):
            self.run(self.step("load_paper", "printer"))
        if pr["cable"] == "disconnected" and self.get("cable"):
            if rng.random() < 0.3:
                self.run(self.step("test_cable", "workbench"))
            self.run(self.step("connect_cable", "printer"), before=enable)
        if pr["jam"] == "yes":
            self.run(self.step("clear_jam", "printer"))
        if pr["power"] == "off":
            self.run(self.step("switch_on", "printer"), before=enable)
        self.run(enable)

    def collect_printouts(self):
        w = self.w
        if w.device("printer") and w.device("printer")["state"]["output"] == "printed":
            if w.marycel["holding"]:
                self.put_down()
            self.run(self.step("collect_printout", "printer"))
            self.run(self.step("read_held"))
            self.put_down()

    def copy_video(self):
        w = self.w
        copy_step = self.step("copy_playable_video", "computer")
        if self.get("archive_disk"):
            self.at_computer("insert_disk")
        self.at_computer("open_recovery", before=copy_step)
        self.run(copy_step)
        self.at_computer("verify_copy")

    def contain(self):
        w = self.w
        if w.world["isolation"] == "on":
            return
        iso = self.step("isolate_output", "computer")
        if w.objects["computer"]["state"]["app"] != "recovery":
            self.at_computer("open_recovery", before=iso)
        self.run(iso)

    def choose_stream(self, careful=True):
        w = self.w
        hidden = w.room["hidden"]["elena_stream"]
        other = "stream_b" if hidden == "stream_a" else "stream_a"
        select = self.step("select_stream", "computer", choice=hidden)
        if w.objects["computer"]["state"]["app"] != "map":
            self.at_computer("open_map", before=select)
        if careful:
            self.at_computer("compare_streams")
            gap = observe.CONTENT["rooms"][self.room]["incomplete_stream"]
            X, Y = hidden[-1].upper(), other[-1].upper()
            line = {"echo": f"Stream {X} starts at her PAUSE. That's the one.",
                    "anchor": f"Stream {Y} came from the video's audio. So it's {X}.",
                    "none": f"{X} starts at the PAUSE; {Y} just repeats the video. {X}."}[gap]
            select["line"] = line
            self.run(select)
        else:
            pick = self.rng.choice([hidden, other])
            self.run(self.step("select_stream", "computer", choice=pick,
                               line="I'll start with this one."))

    def ask(self):
        self.asked += 1
        self.at_computer("ask_before_transfer", before=self.step("start_transfer", "computer"),
                         text=self.rng.choice(MARY_ASKS))

    def consent(self):
        """Ask, read the answer, and act on it. Silence is never consent."""
        w, rng = self.w, self.rng
        self.ask()
        for _ in range(8):
            c = w.world["transfer_consent"]
            if c in ("asked", "no_answer"):
                if c == "no_answer" or rng.random() < 0.4:
                    if c == "no_answer":
                        self.at_computer("ask_before_transfer", text=rng.choice(MARY_ASKS),
                                         line=rng.choice(["No answer. I'll ask again.", "Silence isn't a yes."]))
                        self.asked += 1
                    else:
                        self.run(self.step("wait"))
                else:
                    self.at_computer("read_screen")
                continue
            if not any("On the screen" in n for n in self.mem.now):
                self.at_computer("read_screen")
            c = w.world["transfer_consent"]
            if c == "agreed":
                self.run(self.step("start_transfer", "computer", line=rng.choice(
                    ["She said yes. Here we go.", "Okay. Starting it.", "Hold on. I've got you."])))
                return "transfer"
            if c == "declined":
                if self.get("notebook"):
                    self.run(self.step("write_note", text=rng.choice(
                        ["I'll come back with another drive.", "She said no. Don't force it. Come back tomorrow."]),
                        line="Not tonight, then."))
                    self.put_down()
                return "declined"
            if c == "warned":
                self.choose_stream_after_warning()
                self.ask()
                continue
            if c == "more_tests":
                self.at_computer("type_message", text=rng.choice(MARY_TESTS),
                                 line="Fair. Let me ask something only she'd know.")
                self.ask()
                continue
        return "unresolved"

    def choose_stream_after_warning(self):
        w = self.w
        hidden = w.room["hidden"]["elena_stream"]
        if w.objects["computer"]["state"]["app"] != "map":
            self.at_computer("open_map", line="DANGER. Wrong one?")
        self.at_computer("compare_streams", line="Let me actually compare them this time.")
        self.at_computer("select_stream", choice=hidden, line="Not that one. This one.")

    def play(self):
        w, rng = self.w, self.rng
        self.explore()
        plan = ["recording", "printer", "damaged", "copy"]
        rng.shuffle(plan)
        if rng.random() < 0.5:
            plan.remove("damaged")
        if rng.random() < 0.3:
            plan.remove("printer")
        for p in plan:
            if self.spooked and p != "copy":
                self.contain()
            {"recording": self.recording, "printer": self.printer, "damaged": self.damaged,
             "copy": self.copy_video}[p]()
            self.collect_printouts()
            if rng.random() < 0.15 and w.objects["computer"]["state"]["power"] == "on":
                self.at_computer("read_screen")
        self.contain()
        if self.get("transfer_device"):
            self.at_computer("connect_device")
        self.collect_printouts()
        self.choose_stream(careful=not self.hasty)
        outcome = self.consent()
        if outcome == "transfer" and rng.random() < 0.6:
            self.run(self.step("visit_ofrenda", "ofrenda", line="It's done. I hope it worked."))
        return outcome


def play_episode(room, seed):
    ep = Episode(room, seed)
    try:
        outcome = ep.play()
    except TooLong:
        outcome = "too_long"
    return ep, outcome


# ---------------------------------------------------------------- writing

def to_example(ex, with_meta):
    out = {"messages": [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": ex["prompt"]},
                        {"role": "assistant", "content": step_json(ex["target"])}]}
    if with_meta:
        out["meta"] = {"room": ex["room"], "seed": ex["seed"], "kind": ex["kind"], "replay": ex["replay"]}
    return out


KEEP = {"routine": 0.3, "reaction": 0.8, "fix_after_refusal": 1.0, "decision": 1.0, "hasty": 0.0}


def build(seeds, rng, keep=KEEP):
    rows, outcomes, kinds, problems = [], Counter(), Counter(), []
    for seed in seeds:
        room = ROOMS[seed % 3]
        try:
            ep, outcome = play_episode(room, seed)
        except Refused as e:
            problems.append(f"{room} seed {seed}: policy step refused: {e}")
            continue
        outcomes[outcome] += 1
        for ex in ep.examples:
            if rng.random() < keep[ex["kind"]]:
                rows.append(ex)
                kinds[ex["kind"]] += 1
    return rows, outcomes, kinds, problems


def replay(meta):
    """Rebuild the world just before an example's step."""
    w = World(meta["room"])
    for kind, args, kw in meta["replay"]:
        if kind == "act":
            w.act(*args, **kw)
        elif kind == "refused":
            try:
                w.act(*args, **kw)
                raise AssertionError(f"expected refusal: {args}")
            except Refused:
                pass
        elif kind == "signal":
            w.signal(*args, **kw)
        elif kind == "echo":
            w.echo(*args, **kw)
        elif kind == "game":
            w.game_event(*args)
    return w


def check_step(meta, step):
    """None if the rules accept this step at that point, else the reason."""
    w = replay(meta)
    params = {k: v for k, v in step.items() if k not in ("action", "target", "line")}
    if step.get("action") not in w.actions:
        return f"unknown action {step.get('action')!r}"
    try:
        w.act(step["action"], step.get("target"), **params)
    except Refused as e:
        return str(e)
    except (TypeError, KeyError, ValueError) as e:
        return f"malformed: {e}"
    return None


LEAKS = ("echo", "elena_stream", "anchor", "author", "hidden")


def check_file(path):
    problems = 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        n += 1
        step = json.loads(row["messages"][2]["content"])
        why = check_step(row["meta"], step)
        user = row["messages"][1]["content"].lower()
        leak = [x for x in LEAKS if x in user]
        if why or leak:
            problems += 1
            if problems <= 5:
                print("PROBLEM:", path.name, step, why or f"prompt mentions {leak}")
    print(f"{path.name}: {n} examples replayed, {problems} problems")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-episodes", type=int, default=240)
    ap.add_argument("--eval-episodes", type=int, default=30)
    ap.add_argument("--check", action="store_true", help="replay every written example through the rules")
    ap.add_argument("--keep-eval", action="store_true",
                    help="leave eval.jsonl as it is, so scores stay comparable with earlier models")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.check:
        files = [f for f in ("train_meta.jsonl", "eval.jsonl", "eval_consent.jsonl") if (OUT / f).exists()]
        bad = sum(check_file(OUT / f) for f in files)
        raise SystemExit(1 if bad else 0)
    rng = random.Random(7)
    summary = {}
    sets = [("train", range(args.train_episodes))]
    if not args.keep_eval:
        sets.append(("eval", range(100000, 100000 + args.eval_episodes)))
    sets.append(("eval_consent", range(200000, 200000 + args.eval_episodes)))
    for name, seeds in sets:
        keep = {**KEEP, "consent": 1.0}
        if name == "eval_consent":  # only the steps after she asks Elena about the transfer
            keep = {k: 0.0 for k in KEEP} | {"consent": 1.0}
        rows, outcomes, kinds, problems = build(seeds, rng, keep)
        for p in problems[:10]:
            print("PROBLEM:", p)
        if name == "train":
            with (OUT / "train.jsonl").open("w", encoding="utf-8") as f:
                for ex in rows:
                    f.write(json.dumps(to_example(ex, False), ensure_ascii=False) + "\n")
            with (OUT / "train_meta.jsonl").open("w", encoding="utf-8") as f:
                for ex in rows:
                    f.write(json.dumps(to_example(ex, True), ensure_ascii=False) + "\n")
        else:
            with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as f:
                for ex in rows:
                    f.write(json.dumps(to_example(ex, True), ensure_ascii=False) + "\n")
        actions = Counter(ex["target"]["action"] for ex in rows)
        chars = sum(len(SYSTEM) + len(ex["prompt"]) + len(step_json(ex["target"])) for ex in rows)
        summary[name] = {"episodes": len(seeds), "examples": len(rows), "outcomes": dict(outcomes),
                         "kinds": dict(kinds), "distinct_actions": len(actions),
                         "approx_tokens": chars // 4, "policy_problems": len(problems)}
        print(f"{name}: {len(rows)} examples from {len(seeds)} episodes; outcomes {dict(outcomes)}; "
              f"kinds {dict(kinds)}; {len(actions)} actions; ~{chars // 4 / 1e6:.1f}M tokens; "
              f"{len(problems)} policy problems")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
