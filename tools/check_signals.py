"""Check that the game's signal panel offers a signal exactly when sending it would work.

The server tells the panel which signals work in each room right now (Room.signals_now in
game/server.py). This replays generated nights and, before every one of Marycel's steps,
compares that answer with what actually happens when each signal is sent to a copy of the
room. It also prints the first step at which each signal worked, per room.

    .venv/Scripts/python tools/check_signals.py [nights per room]
"""

from __future__ import annotations

import copy
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "game"))

import make_dataset as md  # noqa: E402
import server  # noqa: E402
from sim import Refused  # noqa: E402


def send_works(w, sid) -> bool:
    s = w.signals[sid]
    params = {}
    if "text" in s["params"]:
        params["text"] = "HI"
    if s.get("choices"):
        params["choice"] = s["choices"][0]
    try:
        copy.deepcopy(w).signal(sid, **params)
        return True
    except Refused:
        return False


def main() -> None:
    nights = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    mismatches, first = [], defaultdict(list)
    for room in server.ROOMS:
        for seed in range(nights):
            ep = md.Episode(room, seed)
            seen, step = set(), [0]
            do = ep.do

            def checked_do(s, *a, ep=ep, seen=seen, step=step, room=room, seed=seed, do=do, **kw):
                r = server.Room(room, 0)
                r.w = ep.w
                now = r.signals_now()
                for sid, offered in now.items():
                    works = send_works(ep.w, sid)
                    if offered != works:
                        mismatches.append((room, seed, step[0], sid, offered, works))
                    if works and sid not in seen:
                        seen.add(sid)
                        first[(room, sid)].append(step[0])
                step[0] += 1
                return do(s, *a, **kw)

            ep.do = checked_do
            try:
                ep.play()
            except md.TooLong:
                pass
    for room in server.ROOMS:
        print(room)
        for sid in ep.w.signals:
            steps = first.get((room, sid), [])
            when = f"first works at step {min(steps)}-{max(steps)} in {len(steps)}/{nights} nights" if steps else "never worked"
            print(f"  {sid:18} {when}")
    print(f"{len(mismatches)} mismatches between the panel and a real send")
    for m in mismatches[:10]:
        print("  ", m)
    sys.exit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
