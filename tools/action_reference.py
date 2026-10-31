"""Write data/ACTIONS.md: every Marycel action and Elena signal in plain words,
grouped by object, generated from data/catalog.json so it never drifts.

    .venv/Scripts/python tools/action_reference.py
"""

from __future__ import annotations

import room_data

OUT = room_data.DATA / "ACTIONS.md"


def _vals(v) -> str:
    v = v if isinstance(v, list) else [v]
    return " or ".join(str(x) for x in v)


def _is(t: dict) -> str:
    return f"is {_vals(t['is'])}" if "is" in t else f"is not {_vals(t['not'])}"


def cond(t: dict) -> str:
    if "any" in t:
        return "either (" + ") or (".join("; ".join(cond(x) for x in b) for b in t["any"]) + ")"
    if "device" in t:
        return f"{t['device']} {t['state']} {_is(t)}"
    if "state" in t:
        return f"{t['state']} {_is(t)}"
    if "world" in t:
        return f"story {t['world']} {_is(t)}"
    if "marycel" in t:
        if t["marycel"] == "seated":
            return f"she is {'seated' if t['is'] == 'yes' else 'standing'}"
        return f"she is {_vals(t['is']).replace('_', ' ')}"
    if "free_slot" in t:
        return "a free slot"
    if "holding" in t:
        h = t["holding"]
        return "hands free" if h is None else "holding something" if h == "*" else f"holding {h}"
    if "item_in_target" in t:
        return "an item is there"
    if "item_state" in t:
        return f"{t['item_state'].replace('.', ' ')} {_is(t)}"
    if "unlocked" in t:
        return f"'{t['unlocked']}' unlocked"
    return str(t)


def effect(t: dict) -> str:
    if "device" in t:
        return f"{t['device']} {t['state']} → {t['set']}"
    if "state" in t:
        return f"{t['state']} → {t['set']}"
    if "world" in t:
        return f"story {t['world']} → {t['set']}"
    if "marycel" in t:
        return f"{t['marycel']} → {t['set'].replace('_', ' ')}"
    if "item_state" in t:
        return f"{t['item_state'].replace('.', ' ')} → {t['set']}"
    if "move_held_to" in t:
        return f"what she holds is now {t['move_held_to']}"
    if "take" in t:
        return "she takes the item" if t["take"] == "*" else f"she takes the {t['take']}"
    if "put_held" in t:
        return "she puts down what she holds"
    if "consume_held" in t:
        return "the held item is used"
    if "create_held" in t:
        return f"she now holds the {t['create_held']}"
    return str(t)


def row(a: dict) -> str:
    reqs = [cond(t) for t in a["requires"]]
    reqs += [f"({k}) " + "; ".join(cond(t) for t in ts) for k, ts in a.get("requires_by_kind", {}).items()]
    req = "; ".join(reqs) or "—"
    effs = [effect(t) for t in a["effects"]]
    effs += ["if " + "; ".join(cond(t) for t in b["when"]) + ": " + "; ".join(effect(t) for t in b["effects"])
             for b in a.get("effects_if", [])]
    if a.get("on_complete"):
        effs.append("when finished: " + "; ".join(effect(t) for t in a["on_complete"]))
    if a.get("on_fail"):
        effs.append("if interrupted by " + ", ".join(a.get("interrupted_by", [])) + ": "
                    + "; ".join(effect(t) for t in a["on_fail"]))
    eff = "; ".join(effs) or "—"
    extra = []
    params = {k: v for k, v in a.get("params", {}).items() if k != "target"}
    if params:
        extra.append("params: " + ", ".join(params))
    if a.get("observes"):
        extra.append(f"learns: {a['observes'].replace('_', ' ')}")
    if a.get("speech"):
        extra.append("she chooses the words")
    if a.get("choices"):
        extra.append("choice: " + ", ".join(a["choices"]))
    if a.get("notes"):
        extra.append(a["notes"])
    return f"| `{a['id']}` | {a['label']} | {req} | {eff} | {a['anim']} | {' '.join(extra)} |"


def main() -> None:
    c = room_data.load_catalog()
    lines = [
        "# Marycel's actions and Elena's signals",
        "",
        "Generated from `data/catalog.json` by `tools/action_reference.py`; edit the catalog, not this file.",
        "",
        f"{len(c['actions'])} actions for Marycel and {len(c['signals'])} signals for Elena. The game checks "
        "every requirement before an action runs; the model can only propose actions from this list.",
        "",
    ]
    # Index: everything she can do with each object or item, shared actions included.
    lines += ["## By object", "", "| Object | Everything she can do with it |", "| --- | --- |"]
    for kind, spec in c["kinds"].items():
        if spec.get("furniture") and kind != "chair":
            continue
        acts = [a["label"] for a in c["actions"] if a["kinds"] != "*" and kind in a["kinds"]]
        lines.append(f"| {spec['label']} | {'; '.join(acts)}; plus walk to and inspect |")
    for item, spec in c["items"].items():
        acts = [a["label"] for a in c["actions"]
                if any(t.get("holding") == item or t.get("take") == item or t.get("create_held") == item
                       or str(t.get("item_state", "")).startswith(item + ".") for t in a["requires"] + a["effects"])]
        if spec.get("readable"):
            acts.append("Read or look at it")
        acts += ["Pick up", "Put down"]
        lines.append(f"| {spec['label']} | {'; '.join(dict.fromkeys(acts))} |")
    lines.append("")
    groups: dict[str, list[dict]] = {}
    for a in c["actions"]:
        groups.setdefault(a["group"], []).append(a)
    head = "| Action | What she does | Needs | Changes | Animation | Notes |\n| --- | --- | --- | --- | --- | --- |"
    for g, acts in groups.items():
        lines += [f"## {g}", "", head] + [row(a) for a in acts] + [""]
    lines += ["## Elena's signals", "",
              "| Signal | What Elena does | Stage | Needs | Marycel notices it when | Notes |",
              "| --- | --- | --- | --- | --- | --- |"]
    for s in c["signals"]:
        req = "; ".join(cond(t) for t in s["requires"]) or "—"
        seen = []
        for p in s["perceived_if"]:
            bits = []
            if "marycel_within" in p:
                bits.append(f"within {p['marycel_within']} px and facing it")
            if "doing" in p:
                bits.append(f"she is doing {p['doing']}")
            if p.get("in_room"):
                bits.append(f"she is in the room ({p.get('route')})")
            elif "route" in p:
                bits.append(f"through {p['route']}")
            seen.append(" ".join(bits))
        note = " ".join(x for x in [
            f"up to {s['max_chars']} characters." if "max_chars" in s else "",
            ("Choices: " + ", ".join(s["choices"]) + ".") if s.get("choices") else "",
            s.get("notes", "")] if x)
        lines.append(f"| `{s['id']}` | {s['label']} | {s['stage']} | {req} | {' or '.join(seen) or '—'} | {note} |")
    lines += ["", "## Game events", "", c["game_events"]["notes"], ""]
    lines += [f"- `{e['id']}` ({e['label']}, after {e['after']}): needs " + "; ".join(cond(t) for t in e["requires"])
              + "; changes " + "; ".join(effect(t) for t in e["effects"]) for e in c["game_events"]["events"]]
    lines += ["", "## Unlocks", ""] + [f"- **{k}**: {v}" for k, v in c["unlocks"].items()]
    lines += ["", "## Story state", "", c["world"]["notes"], ""]
    lines += [f"- **{k}**: {', '.join(v)} (starts {c['world']['start'][k]})" for k, v in c["world"]["states"].items()]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(room_data.ps.ROOT)}")


if __name__ == "__main__":
    main()
