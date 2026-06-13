# Dependency audit & pinning

Clank runs entirely on-box, but it still pulls Python wheels from PyPI at install
time, so every direct dependency is **pinned to an exact version** and was
checked against the genuine, canonical project before pinning. This file is the
record of that audit; the pins live in `requirements.txt` and
`requirements-secure.txt`.

Runtime environment audited: **Python 3.14.5** on the Clank box, verified
2026-06-13 with `pip freeze`.

## Runtime packages

| Package | Pin | Project / publisher | Why we trust it |
|---|---|---|---|
| `numpy` | `2.4.6` | NumPy team | Foundational numerics; ubiquitous. |
| `onnxruntime` | `1.26.0` | Microsoft | Runs Moonshine + the wake-word ONNX on CPU. |
| `tokenizers` | `0.23.1` | Hugging Face | Moonshine's tokenizer. |
| `silero-vad` | `6.2.1` | snakers4 (MIT) | Voice-activity gate. [github.com/snakers4/silero-vad](https://github.com/snakers4/silero-vad) |
| `useful-moonshine-onnx` | `20251121` | Useful Sensors | Moonshine STT inference (ONNX). [pypi.org/project/useful-moonshine-onnx](https://pypi.org/project/useful-moonshine-onnx/) |
| `sounddevice` | `0.5.5` | spatialaudio (PortAudio bindings) | Mic capture. |
| `requests` | `2.34.2` | PSF / requests team | HTTP to the local Ollama LLM. |
| `openwakeword` | `0.4.0` | David Scripka (`dscripka`) | Acoustic "hey clank" gate. [github.com/dscripka/openWakeWord](https://github.com/dscripka/openWakeWord) |
| `PyYAML` | `6.0.3` | PyYAML team | Config + device-registry parsing. |
| `paho-mqtt` | `2.1.0` | Eclipse Foundation (Paho) | Publishes commands to mosquitto. |

Dev-only (not imported at runtime): `pytest==8.4.2`, `black==25.9.0`,
`flake8==7.3.0`.

`openwakeword` is held at **0.4.0 on purpose**: it's the last release installable
on Python 3.14 (later releases need `tflite-runtime`, which has no 3.14 wheel),
it's ONNX-only, and it bundles its models so it runs fully offline.

## The part that actually matters: the ONNX models

Pinning wheels stops a *package* from changing under us. It does **not** vet the
model weights — and ONNX is an executable graph format, so a malicious or
swapped `.onnx` is the real risk. Clank handles model files separately:

- **Moonshine STT** weights are fetched from an immutable Hugging Face commit by
  `scripts/fetch_moonshine.sh` and checked against `SHA256SUMS`
  (`sha256sum -c SHA256SUMS` from the repo root).
- **Wake-word models** (the openWakeWord bundled feature models, the builtins,
  and our own `models/wakeword/hey_clank.onnx`) are SHA256-pinned in
  `_KNOWN_OWW_SHA256` in `src/voicecommand/voice_LED_control.py` and
  integrity-checked **before** `onnxruntime` is allowed to touch them. A known
  model that fails its hash is refused; an unknown model logs its hash so you
  can audit and pin it.

When you train a **new** `hey_clank.onnx`, you must re-audit and re-pin it — see
[training-wakeword.md](training-wakeword.md), which uses
`scripts/train_wakeword/audit_onnx.py` to do the structural check and print the
hash to paste back into `_KNOWN_OWW_SHA256`.

## Re-verifying / re-pinning

```fish
# What's actually installed right now:
.venv/bin/pip freeze

# Confirm a package's publisher/history before bumping a pin:
.venv/bin/pip index versions <package>

# Model integrity:
sha256sum -c SHA256SUMS          # Moonshine
# wake models are checked automatically at Clank startup
```

After bumping any pin: re-test, then update the table above.
