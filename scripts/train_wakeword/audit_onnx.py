#!/usr/bin/env python3
"""Audit a (freshly trained) wake-word ONNX before trusting it, and print the
SHA256 line to pin in Clank.

ONNX is an executable graph format, so a model file is code. Before a new
hey_clank.onnx is allowed anywhere near onnxruntime on the Clank box, it must
pass the same bar as every other model we ship:

  * opset domains are standard only ("" / ai.onnx / ai.onnx.ml) — no custom
    operator domains (a custom domain can mean a custom .so is loaded);
  * no external-data tensors (weights must be in-file, not a sidecar the loader
    would fetch);
  * no embedded URLs / absolute paths / metadata that points off-box;
  * it loads under the stock onnxruntime CPU provider.

On success it prints the exact line to paste into _KNOWN_OWW_SHA256 in
src/voicecommand/voice_LED_control.py.

Usage (in the training env, which has `onnx` installed):

    python scripts/train_wakeword/audit_onnx.py models/wakeword/hey_clank.onnx

Exit code is non-zero if any hard check fails.
"""

import argparse
import hashlib
import os
import re
import sys

# Domains that ship with stock onnxruntime. Anything else means a custom op,
# which can pull in native code — reject.
_STD_DOMAINS = {"", "ai.onnx", "ai.onnx.ml"}

# Look for anything that points off the box inside metadata / the raw bytes.
_OFFBOX = re.compile(rb"https?://|file://|\\\\|/home/|/Users/|[A-Za-z]:\\")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", help="Path to the .onnx file to audit.")
    args = ap.parse_args()

    if not os.path.exists(args.model):
        sys.exit(f"No such file: {args.model}")

    try:
        import onnx
    except ImportError:
        sys.exit("This audit needs the `onnx` package: pip install onnx "
                 "(install it in your training env, not the Clank runtime).")

    digest = sha256_file(args.model)
    size = os.path.getsize(args.model)
    print(f"file   : {args.model}")
    print(f"size   : {size:,} bytes")
    print(f"sha256 : {digest}\n")

    model = onnx.load(args.model)
    problems = []
    notes = []

    # 1) Structural validity.
    try:
        onnx.checker.check_model(model)
        print("[ok] onnx.checker passed")
    except Exception as e:
        problems.append(f"onnx.checker failed: {e}")

    # 2) Opset / operator domains.
    opset_domains = {op.domain for op in model.opset_import}
    bad_opset = opset_domains - _STD_DOMAINS
    versions = ", ".join(f"{op.domain or 'ai.onnx'}={op.version}"
                         for op in model.opset_import)
    print(f"[..] opset: {versions}")
    if bad_opset:
        problems.append(f"non-standard opset domain(s): {sorted(bad_opset)}")

    op_types = {}
    custom_nodes = []
    for node in model.graph.node:
        op_types[node.op_type] = op_types.get(node.op_type, 0) + 1
        if node.domain not in _STD_DOMAINS:
            custom_nodes.append(f"{node.op_type}@{node.domain}")
    print(f"[..] op types ({len(op_types)}): "
          + ", ".join(f"{k}×{v}" for k, v in sorted(op_types.items())))
    if custom_nodes:
        problems.append(f"custom-domain operators: {sorted(set(custom_nodes))}")
    else:
        print("[ok] all operators are in standard domains")

    # 3) External data — weights must be in-file.
    ext = []
    for init in model.graph.initializer:
        if init.data_location == onnx.TensorProto.EXTERNAL or init.external_data:
            ext.append(init.name)
    if ext:
        problems.append(f"tensors stored as EXTERNAL data: {ext[:5]}"
                        + (" …" if len(ext) > 5 else ""))
    else:
        print("[ok] no external-data tensors (weights are in-file)")

    # 4) Metadata props.
    if model.metadata_props:
        for p in model.metadata_props:
            line = f"{p.key}={p.value}"
            if _OFFBOX.search(line.encode("utf-8", "ignore")):
                problems.append(f"metadata points off-box: {line}")
            else:
                notes.append(f"metadata: {line}")
    else:
        print("[ok] no metadata_props")

    # 5) Raw byte scan for off-box references / absolute paths.
    with open(args.model, "rb") as fh:
        raw = fh.read()
    hits = sorted({m.group(0).decode("latin-1") for m in _OFFBOX.finditer(raw)})
    if hits:
        problems.append(f"off-box references in bytes: {hits[:8]}")
    else:
        print("[ok] no URLs / absolute paths in raw bytes")

    # 6) Actually load it under stock CPU onnxruntime.
    try:
        import onnxruntime as ort
        ort.InferenceSession(args.model, providers=["CPUExecutionProvider"])
        print("[ok] loads under onnxruntime CPUExecutionProvider")
    except ImportError:
        notes.append("onnxruntime not in this env — skipped the load test")
    except Exception as e:
        problems.append(f"onnxruntime failed to load it: {e}")

    if notes:
        print("\nnotes:")
        for n in notes:
            print(f"  - {n}")

    print()
    if problems:
        print("AUDIT FAILED — do NOT pin or ship this model:")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)

    name = os.path.basename(args.model)
    print("AUDIT PASSED ✓")
    print("\nPin it: add this line to _KNOWN_OWW_SHA256 in "
          "src/voicecommand/voice_LED_control.py")
    print(f'    "{name}": "{digest}",')
    print("\nand re-run SHA256SUMS if this file is tracked:")
    print(f"    sha256sum {args.model}")


if __name__ == "__main__":
    main()
