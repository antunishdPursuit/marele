"""Runs a local Ollama model on the held-out set and writes its replies for
tools/score_steps.py. Resumes where a previous run stopped.

    .venv/Scripts/python tools/run_ollama.py qwen3:8b data/training/baseline_qwen3_8b.jsonl [--limit N]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

from make_dataset import OUT

URL = "http://127.0.0.1:11434/api/chat"


def chat(model, messages):
    body = {"model": model, "messages": messages, "stream": False, "think": False,
            "options": {"temperature": 0, "num_ctx": 6144, "num_predict": 200}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--eval", default="eval")
    args = ap.parse_args()
    rows = [json.loads(line) for line in (OUT / f"{args.eval}.jsonl").read_text(encoding="utf-8").splitlines()]
    done = set()
    try:
        done = {json.loads(line)["index"] for line in open(args.out, encoding="utf-8")}
    except FileNotFoundError:
        pass
    todo = [i for i in range(len(rows)) if i not in done][:args.limit]
    start = time.time()
    with open(args.out, "a", encoding="utf-8") as f:
        for n, i in enumerate(todo, 1):
            out = chat(args.model, rows[i]["messages"][:2])
            f.write(json.dumps({"index": i, "output": out}, ensure_ascii=False) + "\n")
            f.flush()
            if n % 25 == 0:
                print(f"{n}/{len(todo)} in {time.time() - start:.0f}s", flush=True)
    print(f"done: {len(todo)} replies in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
