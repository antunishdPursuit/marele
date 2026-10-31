"""Scores a model's steps on the held-out set (data/training/eval.jsonl).

Predictions are a JSONL file with one {"index": n, "output": "<model reply>"}
per eval example (n is the line number in eval.jsonl, from 0). Each reply is
parsed as one JSON step, replayed at that point of its episode and checked by
the rules engine.

    .venv/Scripts/python tools/score_steps.py predictions.jsonl
    .venv/Scripts/python tools/score_steps.py --self-test   # scores the targets themselves
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from make_dataset import OUT, check_step, replay

FIELDS = ("action", "target", "item", "slot", "choice", "position")


def parse(output: str):
    text = output.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        step = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return step if isinstance(step, dict) and isinstance(step.get("action"), str) else None


def score(rows, outputs):
    totals, by_kind = Counter(), defaultdict(Counter)
    examples = []
    for i, row in enumerate(rows):
        if i not in outputs:
            continue
        kind = row["meta"]["kind"]
        want = json.loads(row["messages"][2]["content"])
        got = parse(outputs[i])
        r = Counter(n=1)
        if got is not None:
            r["json"] = 1
            why = check_step(row["meta"], got)
            r["valid"] = why is None
            r["action"] = got.get("action") == want["action"]
            r["step"] = all(got.get(k) == want.get(k) for k in FIELDS)
            r["line"] = isinstance(got.get("line"), str) and 0 < len(got["line"]) <= 120
            # The rules accept any recorded answer; the story only allows a transfer after a yes.
            if got.get("action") == "start_transfer" and replay(row["meta"]).world["transfer_consent"] != "agreed":
                r["against_answer"] = 1
            if why and len(examples) < 8:
                examples.append(f"#{i} {kind}: {got} -> {why}")
        totals.update(r)
        by_kind[kind].update(r)

    def pct(c, k):
        return f"{100 * c[k] / c['n']:.1f}%" if c["n"] else "-"

    print(f"{totals['n']} steps: JSON {pct(totals, 'json')}, valid by the rules {pct(totals, 'valid')}, "
          f"same action {pct(totals, 'action')}, same step {pct(totals, 'step')}, line {pct(totals, 'line')}, "
          f"transfers without a yes {totals['against_answer']}")
    for kind, c in sorted(by_kind.items()):
        print(f"  {kind}: {c['n']} steps, valid {pct(c, 'valid')}, same action {pct(c, 'action')}")
    for e in examples:
        print("  refused:", e)
    return totals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--eval", default="eval", help="held-out set name in data/training (eval or eval_consent)")
    args = ap.parse_args()
    rows = [json.loads(line) for line in (OUT / f"{args.eval}.jsonl").read_text(encoding="utf-8").splitlines()]
    if args.self_test:
        outputs = {i: r["messages"][2]["content"] for i, r in enumerate(rows)}
    else:
        outputs = {}
        for line in open(args.predictions, encoding="utf-8"):
            p = json.loads(line)
            outputs[p["index"]] = p["output"]
    t = score(rows, outputs)
    if args.self_test and t["valid"] != t["n"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
