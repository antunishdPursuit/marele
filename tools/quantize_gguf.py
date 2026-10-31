"""Shrinks a GGUF model to Q5_0 with llama.cpp's Python library, for machines
without a C++ toolchain (Ollama on Windows cannot quantize at import time).
Weight matrices become Q5_0; norms and other 1-D tensors stay as they are.

    .venv/Scripts/python tools/quantize_gguf.py data/models/marycel-v2/marycel-v2-q8_0.gguf data/models/marycel-v2/marycel-v2-q5_0.gguf

Needs llama.cpp's gguf-py (Tools/llama.cpp in Home Codex, or LLAMA_CPP).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LLAMA_CPP = Path(os.environ.get("LLAMA_CPP", Path(__file__).resolve().parents[4] / "Tools" / "llama.cpp"))
sys.path.insert(0, str(LLAMA_CPP / "gguf-py"))

import gguf  # noqa: E402
import numpy as np  # noqa: E402
from gguf.quants import dequantize, quantize, quant_shape_from_byte_shape, quant_shape_to_byte_shape  # noqa: E402

Q = gguf.GGMLQuantizationType


def target(t):
    if len(t.shape) < 2 or t.tensor_type not in (Q.F16, Q.BF16, Q.F32, Q.Q8_0):
        return t.tensor_type
    return Q.Q5_0 if t.shape[0] % 32 == 0 else t.tensor_type


def main(src, dst):
    reader = gguf.GGUFReader(src)
    arch = reader.fields[gguf.Keys.General.ARCHITECTURE].contents()
    writer = gguf.GGUFWriter(dst, arch=arch, endianess=reader.endianess)
    for field in reader.fields.values():
        if field.name == gguf.Keys.General.ARCHITECTURE or field.name.startswith("GGUF."):
            continue
        value = field.contents()
        if field.name == gguf.Keys.General.FILE_TYPE:
            value = gguf.LlamaFileType.MOSTLY_Q5_0
        sub = field.types[-1] if field.types[0] == gguf.GGUFValueType.ARRAY else None
        writer.add_key_value(field.name, value, field.types[0], sub_type=sub)

    plan = []
    for t in reader.tensors:
        qtype = target(t)
        if qtype == t.tensor_type:
            shape = t.data.shape
        else:
            shape = quant_shape_to_byte_shape(quant_shape_from_byte_shape(t.data.shape, t.tensor_type), qtype)
        plan.append((t, qtype))
        if qtype == t.tensor_type:
            writer.add_tensor_info(t.name, shape, t.data.dtype, t.data.nbytes, raw_dtype=qtype)
        else:  # quantized data is stored as bytes
            writer.add_tensor_info(t.name, shape, np.uint8, int(np.prod(shape)), raw_dtype=qtype)

    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_ti_data_to_file()
    for i, (t, qtype) in enumerate(plan, 1):
        data = t.data if qtype == t.tensor_type else quantize(dequantize(t.data, t.tensor_type), qtype)
        writer.write_tensor_data(data, tensor_endianess=reader.endianess)
        if i % 40 == 0:
            print(f"{i}/{len(plan)} tensors", flush=True)
    writer.close()
    print(f"wrote {dst} ({Path(dst).stat().st_size / 1e9:.2f} GB)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
