"""Fine-tunes Marycel's model on Tinker: a LoRA on Qwen3-8B (thinking off, so
it matches the local baseline run with Ollama's think=false), trained on
data/training/train.jsonl from tools/make_dataset.py.

    .venv/Scripts/python tools/train_tinker.py --dry-run     # tokens and cost, no API calls
    .venv/Scripts/python tools/train_tinker.py               # trains (needs TINKER_API_KEY; spends money)
    .venv/Scripts/python tools/train_tinker.py --sample tinker://.../sampler_weights/final
                                                             # writes eval replies for tools/score_steps.py

Runs, logs and checkpoint paths go to data/training/runs/<name>/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from make_dataset import OUT

MODEL = "Qwen/Qwen3-8B"
RENDERER = "qwen3_disable_thinking"
PRICE_TRAIN, PRICE_PREFILL, PRICE_SAMPLE = 0.44, 0.195, 0.60  # USD per million tokens (Tinker, October 2026)
MAX_LENGTH = 6144


def renderer():
    from tinker_cookbook import renderers
    from tinker_cookbook.tokenizer_utils import get_tokenizer
    tok = get_tokenizer(MODEL)
    return renderers.get_renderer(RENDERER, tok), tok


def dry_run(epochs):
    r, tok = renderer()
    rows = [json.loads(line) for line in (OUT / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    lengths = []
    for row in rows:
        model_input, weights = r.build_supervised_example(row["messages"])
        lengths.append(model_input.length)
    total = sum(lengths)
    print(f"{len(rows)} examples, {total / 1e6:.2f}M tokens per epoch, longest {max(lengths)} (limit {MAX_LENGTH})")
    print(f"training cost for {epochs} epoch(s): about ${total * epochs * PRICE_TRAIN / 1e6:.2f}")
    ev = [json.loads(line) for line in (OUT / "eval.jsonl").read_text(encoding="utf-8").splitlines()]
    prompt_tokens = sum(r.build_generation_prompt(e["messages"][:2]).length for e in ev)
    print(f"held-out scoring on Tinker: about ${prompt_tokens * PRICE_PREFILL / 1e6 + len(ev) * 60 * PRICE_SAMPLE / 1e6:.2f}")
    sample = r.build_supervised_example(rows[0]["messages"])[0]
    text = tok.decode(sample.to_ints())
    print("rendered end of one example:\n" + text[-400:])


def train(args):
    from tinker_cookbook import hyperparam_utils
    from tinker_cookbook.supervised import train as sft
    from tinker_cookbook.supervised.data import FromConversationFileBuilder
    from tinker_cookbook.supervised.types import ChatDatasetBuilderCommonConfig

    log_path = Path(os.path.relpath(OUT / "runs" / args.name))
    builder = FromConversationFileBuilder(
        file_path=os.path.relpath(OUT / "train.jsonl").replace("\\", "/"),  # the cookbook reader rejects Windows drive paths
        common_config=ChatDatasetBuilderCommonConfig(
            model_name_for_tokenizer=MODEL, renderer_name=RENDERER,
            max_length=MAX_LENGTH, batch_size=args.batch_size),
    )
    lr = args.lr or hyperparam_utils.get_lr(MODEL)
    print(f"training {MODEL} LoRA rank {args.rank}, lr {lr:.2e}, {args.epochs} epoch(s), batch {args.batch_size}")
    config = sft.Config(
        log_path=str(log_path), model_name=MODEL, recipe_name="marycel-sft", renderer_name=RENDERER,
        dataset_builder=builder, learning_rate=lr, num_epochs=args.epochs, lora_rank=args.rank,
        save_every=50, eval_every=0,
    )
    asyncio.run(sft.main(config))
    print(f"done; checkpoints are listed in {log_path / 'checkpoints.jsonl'}")


async def sample(model_path, out_path, eval_name="eval"):
    import tinker
    from tinker import types

    r, _ = renderer()
    client = tinker.ServiceClient().create_sampling_client(base_model=MODEL, model_path=model_path)
    rows = [json.loads(line) for line in (OUT / f"{eval_name}.jsonl").read_text(encoding="utf-8").splitlines()]
    params = types.SamplingParams(max_tokens=200, temperature=0.0, stop=r.get_stop_sequences())
    sem = asyncio.Semaphore(16)

    async def one(i, row):
        async with sem:
            res = await client.sample_async(prompt=r.build_generation_prompt(row["messages"][:2]),
                                            num_samples=1, sampling_params=params)
            msg, _ = r.parse_response(res.sequences[0].tokens)
            return {"index": i, "output": msg["content"] if isinstance(msg["content"], str) else str(msg["content"])}

    results = await asyncio.gather(*(one(i, row) for i, row in enumerate(rows)))
    with open(out_path, "w", encoding="utf-8") as f:
        for p in results:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"wrote {len(results)} replies to {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", metavar="TINKER_PATH", help="score a trained checkpoint on the held-out set")
    ap.add_argument("--out", default=str(OUT / "finetuned_eval.jsonl"))
    ap.add_argument("--eval", default="eval", help="held-out set name in data/training (eval or eval_consent)")
    ap.add_argument("--name", default="marycel-qwen3-8b-v1")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float)
    args = ap.parse_args()
    if args.dry_run:
        return dry_run(args.epochs)
    env = OUT.parent.parent / ".env"  # optional project-root .env with TINKER_API_KEY=...
    if not os.environ.get("TINKER_API_KEY") and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("TINKER_API_KEY="):
                os.environ["TINKER_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
    if not os.environ.get("TINKER_API_KEY"):
        raise SystemExit("Set TINKER_API_KEY, or put TINKER_API_KEY=... in the project's .env file.")
    if args.sample:
        return asyncio.run(sample(args.sample, args.out, args.eval))
    train(args)


if __name__ == "__main__":
    main()
