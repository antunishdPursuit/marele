"""Marele: game server.

Runs the three rooms with the reference rules engine (tools/sim.py), asks the
Marycel model for each of her steps with exactly the prompt format she was
trained on (tools/make_dataset.py), and serves the browser client in game/web.

    .venv/Scripts/python game/server.py            # local: Ollama, marycel-v2; open http://127.0.0.1:8765
    MARYCEL_MODEL=qwen3:8b .venv/Scripts/python game/server.py

Hosted (Render): MARYCEL_BACKEND=tinker with TINKER_API_KEY samples the same
fine-tuned checkpoint on Tinker. Each visitor gets their own night (a cookie),
and a daily step budget caps what the hosted copy can spend.

The player is Elena: one signal reaches all three rooms, and each Marycel
notices it (or not) from where she is. The Echo is game-driven, as in training.
"""

from __future__ import annotations

import copy
import json
import os
import random
import secrets
import sys
import threading
import time
import posixpath
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from PIL import Image  # noqa: E402

import make_dataset as md  # noqa: E402
import observe  # noqa: E402
import room_data  # noqa: E402
from score_steps import parse  # noqa: E402
from sim import Refused, World  # noqa: E402

BACKEND = os.environ.get("MARYCEL_BACKEND", "ollama")  # ollama (local GPU) or tinker (hosted)
TINKER_MODEL = os.environ.get(
    "TINKER_MODEL", "tinker://d7ed2463-7545-5e1f-ac75-90adaca97337:train:0/sampler_weights/final")  # marycel-v2
TINKER_URL = "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1/completions"
MODEL = TINKER_MODEL if BACKEND == "tinker" else os.environ.get("MARYCEL_MODEL", "marycel-v2")
MODEL_LABEL = "marycel-v2 on Tinker" if BACKEND == "tinker" else MODEL
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
DAILY_STEPS = int(os.environ.get("DAILY_STEP_LIMIT", "6000"))  # hosted budget: about $0.0005 a step on Tinker
KEY_VALUE_URL = os.environ.get("KEY_VALUE_URL")                # a Key Value store keeps that count across restarts
MAX_GAMES = int(os.environ.get("MAX_GAMES", "40"))             # nights kept in memory at once
NEW_GAMES_PER_DAY = int(os.environ.get("NEW_GAMES_PER_DAY", "25"))  # per visitor address
IDLE_SECONDS = 30 * 60                                          # a night nobody touches is dropped
MAX_SILENCES = 3                                                # unanswered transfer questions before her night ends
NIGHT_LOG = os.environ.get("NIGHT_LOG", "1") != "0"             # one JSON line per step, signal and ending
WEB = ROOT / "game" / "web"
ROOMS = md.ROOMS
MAX_STEPS = 120          # a room's night ends after this many of Marycel's steps
LOOP_WINDOW = 12         # ...or when her last this-many steps use only two actions
P_ECHO = 0.25            # chance the Echo repeats an exposed phrase after a step (training: 0.1 to 0.4)
CATALOG = room_data.load_catalog()
PROPS = {p.stem: Image.open(p) for p in (ROOT / "assets" / "pixel" / "props").glob("*.png")}
OLLAMA_LOCK = threading.Lock()  # one GPU: Marycel's steps are generated one at a time
TINKER_SLOTS = threading.BoundedSemaphore(8)


class OutOfBudget(Exception):
    pass


class Budget:
    """Steps the hosted copy may ask Tinker for today (resets at midnight UTC). With KEY_VALUE_URL
    the count lives in that store, so a restart or a sleeping server doesn't reset it. Paid
    calls stop while the store is unavailable; local inference may count in memory."""

    def __init__(self, limit: int, url: str | None = None):
        self.limit, self.day, self.used, self.lock = limit, "", 0, threading.Lock()
        self.store, self.store_down = None, False
        if url:
            import redis  # only the hosted copy needs it (requirements.txt)
            self.store = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)

    def take(self):
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self.store is not None:
            try:
                key = f"marele:steps:{today}"
                used, _ = self.store.pipeline().incr(key).expire(key, 2 * 86400).execute()
                self.store_down = False
                return self._check(used)
            except OutOfBudget:
                raise
            except Exception as e:
                if not self.store_down:
                    print(f"step budget store unavailable ({type(e).__name__}); paid calls paused", file=sys.stderr)
                self.store_down = True
                raise OutOfBudget("The shared step budget is unavailable. Please try again later.") from e
        if BACKEND == "tinker":
            raise OutOfBudget("The shared step budget is not configured. Please try again later.")
        with self.lock:
            if today != self.day:
                self.day, self.used = today, 0
            self.used += 1
            self._check(self.used)

    def _check(self, used: int):
        if used > self.limit:
            raise OutOfBudget("Marycel has worked enough nights for today. Please come back tomorrow.")


BUDGET = Budget(DAILY_STEPS, KEY_VALUE_URL)


def chat(messages) -> str:
    if BACKEND == "tinker":
        return chat_tinker(messages)
    body = {"model": MODEL, "messages": messages, "stream": False, "think": False, "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_ctx": 6144, "num_predict": 200}}
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with OLLAMA_LOCK, urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["message"]["content"]


def chat_tinker(messages) -> str:
    """The same checkpoint on Tinker, prompted exactly as in training (renderer qwen3_disable_thinking)."""
    BUDGET.take()
    prompt = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
    prompt += "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    body = {"model": TINKER_MODEL, "prompt": prompt, "max_tokens": 200, "temperature": 0.2, "stop": ["<|im_end|>"]}
    req = urllib.request.Request(TINKER_URL, json.dumps(body).encode(), {
        "Content-Type": "application/json", "User-Agent": "marele/1.0",
        "Authorization": "Bearer " + os.environ.get("TINKER_API_KEY", "")})
    with TINKER_SLOTS, urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["text"]


class Room:
    def __init__(self, name: str, seed: int, tag: str = ""):
        self.name, self.tag = name, tag
        self.w = World(name)
        self.mem = md.Memory()
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.steps = 0
        self.ended = False
        self.question = None      # what she typed when she asked about the transfer
        self.heard = 0            # things that reached her since her last step
        self.silences = 0         # transfer questions that went unanswered
        self.paused = False       # the player paused the night: a step that lands meanwhile never happens
        self.why_ended = None     # in plain words, for the player
        self.log: list[dict] = []  # what the player sees: her steps, lines and what reached her

    # ---------------- Marycel

    def step(self, consent_expired: bool = False) -> dict:
        with self.lock:
            if self.ended:
                return {"ended": True}
            self.paused = False  # she is only asked for a step while the night runs
            # the client's answer clock ran out and nothing reached her meanwhile: she has waited,
            # so she gets the step and cue training gave her for silence, and consent becomes
            # no_answer. If Elena sent anything, she steps on that instead. After MAX_SILENCES
            # unanswered questions her night ends rather than asking again and again.
            if consent_expired and self.w.world["transfer_consent"] == "asked" and not self.heard:
                self.w.game_event("consent_timeout")
                self.silences += 1
                if self.silences >= MAX_SILENCES:
                    self.ended, self.why_ended = True, "three of her questions went unanswered"
                    night_log("ended", self, reason="no answer to her question", outcome=self.outcome())
                    return {"ended": True, "why": self.why_ended}
                waited = "You wait. Nothing appears on the screen."
                self.mem.record({"action": "wait"}, waited)
                self.mem.now = [waited]
            messages = [{"role": "system", "content": md.SYSTEM},
                        {"role": "user", "content": md.user_prompt(self.w, self.mem)}]
            shown = len(self.mem.now)  # what reaches her after this point goes into her next prompt
        reply = chat(messages)
        with self.lock:
            if self.ended:  # the night was ended while she was thinking: her step never happens
                return {"ended": True}
            if self.paused:  # paused while she was thinking: nothing happens; she steps again after Resume
                return {"held": True}
            return self._apply(parse(reply), reply, self.mem.now[shown:])

    def _apply(self, s, reply, arrived=()) -> dict:
        w = self.w
        if s is None:  # not one JSON step: nothing happens, and she is told so
            s = {"action": "wait", "line": "..."}
            result, refused = "REFUSED: that step doesn't fit this action here.", True
        else:
            s = {k: v for k, v in s.items() if isinstance(k, str)}
            params = {k: v for k, v in s.items() if k not in ("action", "target", "line")}
            try:
                if s["action"] not in w.actions:
                    raise Refused(f"unknown action {s['action']!r}")
                result = w.act(s["action"], s.get("target"), **params)
                refused = False
                if result is None:
                    result = f"Done: {md.ACTIONS[s['action']]['label'].lower()}."
                if s["action"] == "wait" and w.world["transfer_consent"] == "asked":
                    w.game_event("consent_timeout")
                    result = "You wait. Nothing appears on the screen."
                if s["action"] == "ask_before_transfer":
                    self.question = s.get("text")
            except Refused as e:
                result, refused = f"REFUSED: {md.explain(e, w, s.get('target'))}.", True
            except (TypeError, KeyError, ValueError, AttributeError):
                result, refused = "REFUSED: that step doesn't fit this action here.", True
        self.mem.record(s, result)
        noticed = [] if refused else self._echo()
        self.mem.now = [result] + noticed + list(arrived)
        self.heard = len(arrived)
        self.steps += 1
        action = md.ACTIONS.get(s.get("action"), {})
        entry = {"n": self.steps, "step": {k: v for k, v in s.items() if k != "line"}, "line": s.get("line", ""),
                 "result": result, "refused": refused, "noticed": noticed}
        self.log.append(entry)
        recent = [e["step"].get("action") for e in self.log if "step" in e][-LOOP_WINDOW:]  # her steps only
        if w.world["transfer"] == "completed":
            self.why_ended = "a voice was moved"
        elif s.get("action") == "write_note" and not refused and w.world["transfer_consent"] == "declined":
            self.why_ended = "she left you a note after your No"  # as in training, her note closes the night
        elif len(recent) == LOOP_WINDOW and len(set(recent)) <= 2:
            self.why_ended = "she kept going round in circles, repeating the same steps"
        elif self.steps >= MAX_STEPS:
            self.why_ended = f"she reached the night's limit of {MAX_STEPS} steps"
        self.ended = self.why_ended is not None
        night_log("step", self, n=self.steps, action=s.get("action"), target=s.get("target"),
                  text=s.get("text"), line=s.get("line", ""), refused=refused, result=result[:200],
                  noticed=noticed, arrived=list(arrived), ended=self.ended)
        if self.ended:
            night_log("ended", self, outcome=self.outcome())
        return {**entry, "anim": action.get("anim", "idle"), "ms": action.get("ms", 600), "room": self.snapshot()}

    def _echo(self) -> list[str]:
        """The Echo's turn: it may repeat a phrase Marycel has exposed (game-driven, never the model)."""
        w = self.w
        if not (w.exposed["damaged"] and w.world["isolation"] == "off" and self.rng.random() < P_ECHO):
            return []
        before = len(w.perceived)
        trial = copy.deepcopy(w)
        phrase = self.rng.choice(sorted(w.exposed["damaged"]))
        try:
            trial.echo("echo_repeat_phrase", phrase)
        except Refused:
            return []
        w.echo("echo_repeat_phrase", phrase)
        return [p["text"] for p in w.perceived[before:] if p["from"] == "room"]

    # ---------------- Elena

    def signal(self, sid: str, params: dict) -> dict:
        with self.lock:
            if self.ended:
                return {"status": "ended"}
            w = self.w
            before = len(w.perceived)
            try:
                noticed = w.signal(sid, **params)
            except Refused as e:
                if sid == "transfer_response" and w.world["transfer_consent"] != "asked":
                    return {"status": "unavailable", "why": "she isn't waiting for an answer right now"}
                why = (md.explain(e, w, None) if e.failed else
                       "that channel isn't open yet" if "locked" in str(e) else str(e).replace(f"signal {sid} ", ""))
                for a, b in (("you haven't", "she hasn't"), ("you aren't", "she isn't"), ("you're", "she's"),
                             ("your ", "her "), ("you ", "she ")):  # the reasons are written to Marycel
                    why = why.replace(a, b)
                return {"status": "unavailable", "why": why}
            except (TypeError, KeyError, ValueError) as e:
                return {"status": "unavailable", "why": str(e)}
            texts = [p["text"] for p in w.perceived[before:] if p["from"] == "room"]
            self.mem.now += texts
            self.heard += len(texts)
            route = w.author_log[-1]["route"] if w.author_log else None
            self.log.append({"elena": sid, "params": params, "noticed": texts, "route": route})
            if sid == "transfer_response":
                self.silences = 0  # an answer: "three unanswered" means three in a row
            night_log("signal", self, signal=sid, params=params, noticed=bool(noticed), route=route,
                      at=w.marycel["at"], seated=w.marycel["seated"])
            return {"status": "noticed" if noticed else ("sent" if route else "no_route"), "route": route}

    # ---------------- what the client draws

    def outcome(self) -> dict | None:
        w, world = self.w, self.w.world
        right = world["selected_stream"] == self.w.room["hidden"]["elena_stream"]
        if world["transfer"] == "completed":
            # the Story Bible's bridge also needs the family video saved; without it, half a bridge
            key = ("bridge" if world["video_copy"] == "preserved" else "half_bridge") if right else "wrong_voice"
        elif world["transfer_consent"] == "declined" and world["passage"] in ("contained", "transfer"):
            key = "promise"
        elif world["video_copy"] == "preserved":
            key = "recording_survives"
        else:
            key = "unresolved"
        return {"key": key, "echo": bool(sum(w.outputs["echo"].values())),  # did the Echo ever make a sound
                "video": world["video_copy"], "passage": world["passage"],
                "stream": world["selected_stream"], "elena_stream": self.w.room["hidden"]["elena_stream"],
                "consent": world["transfer_consent"], "steps": self.steps, "why": self.why_ended}

    def signals_now(self) -> dict:
        """Which of Elena's signals would go through in this room right now. The same unlock and
        requires checks World.signal makes, so the panel never offers one that will be refused."""
        w, now = self.w, {}
        for sid, s in w.signals.items():
            dev = w.device(s["device"])
            try:
                now[sid] = bool(w.unlocked(s["unlock"]) and
                                all(w.cond(t, dev["id"] if dev else None, {}) for t in s["requires"]))
            except (KeyError, TypeError, ValueError):
                now[sid] = False
        return now

    def reach(self, now: dict) -> dict:
        """Whether she would notice something on the screen or from the speakers at this moment
        (given signals_now, so a screen that is off is never one she sees)."""
        w = self.w

        def notices(sid):
            dev = w.device(w.signals[sid]["device"])
            try:
                return bool(dev) and observe.perceives_now(w, w.signals[sid]["perceived_if"], dev["id"])
            except (KeyError, TypeError, ValueError):
                return False
        return {"screen": now["screen_message"] and notices("screen_message"),
                "sound": bool(observe.audible_route(w)) and notices("tone")}

    def snapshot(self) -> dict:
        w = self.w
        objs = list(w.objects.values())
        holder = {"objects": objs}
        objects = []
        for o in objs:
            kind = CATALOG["kinds"][o["kind"]]
            sprite = room_data.sprite_for(o, CATALOG) if kind["sprites"] else None
            objects.append({
                "id": o["id"], "kind": o["kind"], "label": kind["label"], "state": o["state"],
                "sprite": sprite, "overlays": [{"sprite": v["sprite"], "dx": v["dx"], "dy": v["dy"]}
                                               for v in room_data.overlays_for(o, CATALOG)],
                "bounds": room_data.bounds(o, CATALOG, PROPS), "stand_x": o.get("stand_x"),
                "sit_x": o.get("sit_x"), "facing": o.get("facing", "left"),
                "outline": bool(sprite and sprite + "_outline" in PROPS)})
        items = []
        for i in w.items.values():
            visible = not (i["id"] == w.marycel["holding"] or i.get("worn") or i.get("at") or
                           ("in" in i and w.objects[i["in"]]["state"].get("open") == "no"))
            pos = room_data.item_position(i, holder, CATALOG, PROPS) if visible and ("on" in i or "floor_x" in i) else None
            items.append({"id": i["id"], "kind": i["kind"], "label": CATALOG["items"][i["kind"]]["label"],
                          "sprite": CATALOG["items"][i["kind"]]["sprite"], "pos": pos})
        m = w.marycel
        at = w.objects.get(m["at"], {})
        return {
            "id": self.name, "label": w.room["label"], "situation": w.room["situation"],
            "objects": objects, "items": items,
            "marycel": {**m, "x": observe.marycel_x(w), "facing": at.get("facing", "left"),
                        "holding_sprite": CATALOG["items"][w.held()["kind"]]["sprite"] if w.held() else None,
                        "wearing": [CATALOG["items"][i["kind"]]["sprite"] for i in w.items.values() if i.get("worn")]},
            "world": w.world, "screen": w.screen["text"] if w.screen else None,
            "question": self.question if w.world["transfer_consent"] == "asked" else None,
            "unlocked": {k: w.unlocked(k) for k in CATALOG["unlocks"]},
            "signals_now": (now := self.signals_now()), "reach": self.reach(now),
            "sound_route": observe.audible_route(w), "steps": self.steps, "ended": self.ended, "why_ended": self.why_ended,
            "outcome": self.outcome() if self.ended else None,
            "log": self.log[-40:],
        }


def night_log(event: str, room: "Room", **fields):
    """One JSON line per event on stdout (Render keeps it in the service log), so real nights
    can be read back: her steps and lines, Elena's signals with their words, and endings."""
    if NIGHT_LOG:
        try:  # a log line must never break a step
            print("NIGHT " + json.dumps({"night": room.tag, "room": room.name, "event": event, **fields},
                                        default=str), flush=True)
        except Exception:
            pass


class Game:
    def __init__(self, seed=None):
        seed = seed if seed is not None else random.randrange(1 << 30)
        tag = secrets.token_hex(3)  # names this night in the log; nothing about the visitor
        self.rooms = {name: Room(name, seed + i, tag) for i, name in enumerate(ROOMS)}
        self.touched = time.time()

    def state(self):
        return {"model": MODEL_LABEL, "rooms": [r.snapshot() for r in self.rooms.values()],
                "signals": [{"id": s["id"], "label": s["label"], "unlock": s["unlock"],
                             "params": list(s.get("params", {})), "choices": s.get("choices"),
                             "max_chars": s.get("max_chars"), "stage": s.get("stage")} for s in CATALOG["signals"]],
                "fragments": [{"id": f["id"], "label": f.get("label", f["id"])} for f in observe.CONTENT["machine"]["fragments"]],
                # what Elena can say: only the words and notes Marycel was trained on (no free typing)
                "phrases": {"screen": md.ELENA_SCREEN, "answers": md.ELENA_ANSWERS, "notes": md.ELENA_NOTES,
                            "prints": md.ELENA_PRINTS},
                "files": [{"id": f["id"], "name": f["name"]} for f in observe.CONTENT["machine"]["files"]]}

    def pause(self, on: bool):
        for r in self.rooms.values():
            r.paused = on

    def end(self):
        for r in self.rooms.values():
            with r.lock:
                if not r.ended:
                    night_log("ended", r, reason="the player ended the night", outcome=r.outcome())
                    r.why_ended = "you ended the night"
                r.ended = True


class Nights:
    """One night per visitor, found by a cookie; idle nights are dropped."""

    def __init__(self):
        self.games: dict[str, Game] = {}
        self.started: dict[tuple[str, str], int] = {}  # (day, address) -> nights started
        self.lock = threading.Lock()

    def get(self, sid: str | None) -> Game | None:
        with self.lock:
            g = self.games.get(sid or "")
            if g:
                g.touched = time.time()
            return g

    def new(self, address: str, seed=None) -> tuple[str, Game]:
        with self.lock:
            now = time.time()
            for sid in [s for s, g in self.games.items() if now - g.touched > IDLE_SECONDS]:
                del self.games[sid]
            key = (time.strftime("%Y-%m-%d", time.gmtime()), address)
            self.started = {k: v for k, v in self.started.items() if k[0] == key[0]}
            if self.started.get(key, 0) >= NEW_GAMES_PER_DAY:
                raise OutOfBudget("You've started a lot of nights today. Please come back tomorrow.")
            if len(self.games) >= MAX_GAMES:
                raise OutOfBudget("Every room is busy right now. Please try again in a few minutes.")
            self.started[key] = self.started.get(key, 0) + 1
            sid, game = secrets.token_urlsafe(16), Game(seed)
            self.games[sid] = game
            return sid, game


NIGHTS = Nights()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))

    def end_headers(self):
        # game files are revalidated on every load (a 304 when unchanged), so a page loaded
        # after a deploy gets the new sprites, manifest and script, not old cached copies
        if not self.path.startswith("/api/") and "Cache-Control" not in "".join(
                h.decode("latin-1") for h in getattr(self, "_headers_buffer", [])):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def handle(self):
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # the browser cancelled (e.g. it seeks in a music file); nothing to answer

    def _json(self, obj, code=200, sid=None):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if sid:
            self.send_header("Set-Cookie", f"night={sid}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(data)

    def _sid(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c["night"].value if "night" in c else None

    def _address(self):  # behind Render's proxy the visitor's address is the first forwarded one
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def send_head(self):
        """Static files with HTTP Range support, so the browser can seek in music and knows its length."""
        rng = self.headers.get("Range", "")
        path = Path(self.translate_path(self.path))
        if not rng.startswith("bytes=") or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        start_s, _, end_s = rng[6:].split(",")[0].partition("-")
        try:
            start = int(start_s) if start_s else max(0, size - int(end_s))
            end = min(int(end_s), size - 1) if start_s and end_s else size - 1
        except ValueError:
            return super().send_head()
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        f = path.open("rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._range_left = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        left = getattr(self, "_range_left", None)
        if left is None:
            return super().copyfile(source, outputfile)
        self._range_left = None
        while left > 0:
            chunk = source.read(min(65536, left))
            if not chunk:
                break
            outputfile.write(chunk)
            left -= len(chunk)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.path = "/game/web/index.html"
        if self.path == "/api/state":
            game = NIGHTS.get(self._sid())
            return self._json(game.state()) if game else self._json({"error": "No night started."}, 404)
        # decode and normalise first, so "/assets/..%2f.env" can't step outside the two folders
        clean = posixpath.normpath(urllib.parse.unquote(urllib.parse.urlsplit(self.path).path))
        if not clean.startswith(("/game/web/", "/assets/")):
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        try:
            body = self._body()
            if self.path == "/api/new":
                sid, game = NIGHTS.new(self._address(), body.get("seed"))
                return self._json(game.state(), sid=sid)
            game = NIGHTS.get(self._sid())
            if game is None:
                return self._json({"error": "This night has ended. Press End the night, then Play again."}, 410)
            if self.path == "/api/step":
                room = game.rooms[body["room"]]
                return self._json(room.step(consent_expired=bool(body.get("consent_expired"))))
            if self.path == "/api/signal":
                sid, params = body["signal"], body.get("params") or {}
                results = {name: r.signal(sid, params) for name, r in game.rooms.items()}
                return self._json({"results": results, "rooms": [r.snapshot() for r in game.rooms.values()]})
            if self.path == "/api/pause":
                game.pause(bool(body.get("paused")))
                return self._json({"paused": bool(body.get("paused"))})
            if self.path == "/api/end":
                game.end()
                return self._json(game.state())
        except OutOfBudget as e:
            return self._json({"error": str(e)}, 429)
        except urllib.error.HTTPError as e:
            return self._json({"error": f"The model service answered {e.code}. Trying again..."}, 503)
        except urllib.error.URLError as e:
            where = "Tinker" if BACKEND == "tinker" else f"Ollama at {OLLAMA}"
            return self._json({"error": f"Can't reach {where} ({e.reason}). Is it running?"}, 503)
        except Exception as e:  # report, keep serving
            print(f"error on {self.path}: {type(e).__name__}: {e}", flush=True)
            return self._json({"error": "Something went wrong on the server. Please try again."}, 500)
        return self.send_error(404)


def main():
    if BACKEND == "tinker" and not os.environ.get("TINKER_API_KEY"):
        sys.exit("MARYCEL_BACKEND=tinker needs TINKER_API_KEY in the environment.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Marele on http://{HOST}:{PORT} (model {MODEL_LABEL})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
