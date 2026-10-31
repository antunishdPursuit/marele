"""Brings a Tinker-trained Marycel model to this machine for Ollama: downloads
the LoRA adapter from a training checkpoint, merges it into Qwen3-8B,
converts it to GGUF with llama.cpp (Ollama 0.40 on Windows cannot import
safetensors: that path needs MLX), shrinks it to Q5_0 with tools/quantize_gguf.py
so it fits a 10 GB GPU, and imports it into Ollama with the base qwen3:8b chat
template (thinking off is chosen per request, as in tools/run_ollama.py).

    .venv/Scripts/python tools/export_model.py --step adapter   # needs TINKER_API_KEY and a Tinker balance
    .venv/Scripts/python tools/export_model.py --step merge     # downloads Qwen/Qwen3-8B (about 16 GB) once
    .venv/Scripts/python tools/export_model.py --step ollama    # GGUF, Q5_0, ollama create marycel-v2
    .venv/Scripts/python tools/export_model.py                  # all three

Files go to data/models/<name>/; the ollama step deletes the merged copy and
the 8-bit GGUF afterwards, keeping the adapter and <name>-q5_0.gguf. The
converter is llama.cpp's convert_hf_to_gguf.py (Tools/llama.cpp in Home Codex,
or LLAMA_CPP; it also needs the sentencepiece package).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from make_dataset import OUT
from quantize_gguf import LLAMA_CPP
from quantize_gguf import main as quantize
from train_tinker import MODEL

MODELS = OUT.parent / "models"
V2 = "tinker://d7ed2463-7545-5e1f-ac75-90adaca97337:train:0/weights/final"


def load_key():
    env = OUT.parent.parent / ".env"
    if not os.environ.get("TINKER_API_KEY") and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("TINKER_API_KEY="):
                os.environ["TINKER_API_KEY"] = line.split("=", 1)[1].strip().strip('"')


def adapter(args, root):
    from tinker_cookbook import weights
    load_key()
    weights.download(tinker_path=args.checkpoint, output_dir=str(root / "adapter"))
    print("adapter:", sorted(p.name for p in (root / "adapter").iterdir()))


def merge(args, root):
    from tinker_cookbook import weights
    weights.build_hf_model(base_model=MODEL, adapter_path=str(root / "adapter"), output_path=str(root / "merged"))
    print("merged into", root / "merged")


def ollama(args, root):
    base = subprocess.run(["ollama", "show", "qwen3:8b", "--modelfile"], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout
    keep, inside = [], False
    for line in base.splitlines():  # TEMPLATE (multi-line) and PARAMETER lines from the base model
        if line.startswith("TEMPLATE"):
            inside = True
        if inside or line.startswith("PARAMETER"):
            keep.append(line)
        if inside and line.rstrip().endswith('"""') and line.strip() != 'TEMPLATE """':
            inside = False
    q8, q5 = root / f"{args.name}-q8_0.gguf", root / f"{args.name}-q5_0.gguf"
    subprocess.run([sys.executable, str(LLAMA_CPP / "convert_hf_to_gguf.py"), str(root / "merged"),
                    "--outtype", "q8_0", "--outfile", str(q8)], check=True)
    quantize(str(q8), str(q5))
    modelfile = root / "Modelfile"
    modelfile.write_text(f"FROM ./{q5.name}\n" + "\n".join(keep) + "\n", encoding="utf-8")
    subprocess.run(["ollama", "create", args.name, "-f", str(modelfile)], cwd=root, check=True)
    q8.unlink()
    shutil.rmtree(root / "merged")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default=V2, help="tinker://.../weights/<name> training checkpoint")
    ap.add_argument("--name", default="marycel-v2")
    ap.add_argument("--step", choices=["adapter", "merge", "ollama"])
    args = ap.parse_args()
    root = MODELS / args.name
    root.mkdir(parents=True, exist_ok=True)
    for name, fn in (("adapter", adapter), ("merge", merge), ("ollama", ollama)):
        if args.step in (None, name):
            fn(args, root)


if __name__ == "__main__":
    main()
