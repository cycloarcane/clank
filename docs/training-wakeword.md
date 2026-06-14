# Training the "hey clank" wake word

Clank's wake gate is a small openWakeWord ONNX model (`models/wakeword/hey_clank.onnx`).
The shipped model was trained mostly on **synthetic** speech, which is why recall
drops on a microphone it never "heard" during training — the symptom you hit on
the laptop: a headset scores 0.7–0.9 but the built-in mic barely clears 0.1.

The durable fix is to **retrain with audio from the mic Clank actually uses**.
This guide covers doing that on the Clank box itself.

> Security rule for this project: **a `.onnx` is executable graph code.** Any
> model that lands on the Clank box must pass `scripts/train_wakeword/audit_onnx.py`
> and be SHA256-pinned in `_KNOWN_OWW_SHA256` before Clank will load it. Never
> drop an unaudited model into `models/wakeword/`.

---

## Can I train on the laptop? Yes.

VRAM is **not** the bottleneck. openWakeWord's heavy feature extractors
(melspectrogram + embedding) are frozen; you only train a tiny classifier head.
The real costs are:

- **Disk** — the augmentation/negative feature sets are several GB to download.
- **CPU time** — generating synthetic speech (Piper TTS) is the slow step.
- **Setup** — a separate Python 3.11 environment (the runtime venv is 3.14 and
  can't run the training stack).

A 4 GB dGPU is plenty; it'll even run CPU-only, just slower. Budget an evening,
not a weekend. Bonus of training here: you record and train on the *same*
acoustic path Clank listens through.

---

## Two approaches

| | Full retrain | Custom verifier |
|---|---|---|
| Output | a new `hey_clank.onnx` | a `.pkl` verifier on top of a base model |
| Data needed | synthetic + real clips + negatives | ~3 positive + ~10s negative clips |
| Effort | an evening | minutes |
| Fits Clank as-is? | **Yes** — drop-in replacement | No — Clank's loader expects an `.onnx`; using a verifier needs a small code change |

For closing the mic-recall gap, do the **full retrain** — it's the supported,
drop-in path. The verifier is a quick personalization trick but doesn't slot
into Clank's current model loader, so it's noted at the end only.

---

## Full retrain — step by step

### 1. Build the training environment (Python 3.11, separate venv)

```fish
python3.11 -m venv ~/oww-training/.venv
source ~/oww-training/.venv/bin/activate.fish
pip install -r scripts/train_wakeword/requirements-training.txt
```

If a version fails to resolve, the upstream notebook is the source of truth:
<https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb>.
The maintained local/Docker pipeline at
<https://github.com/CoreWorxLab/openwakeword-training> is a good fallback when
the Colab notebook breaks (it often does).

### 2. Record real clips from the Clank mic

This is the step that actually fixes recall. Run it **in the Clank runtime venv**
(it uses `sounddevice`/`soundfile`, which are already there), on the laptop, with
the mic at its sweet spot (~55% gain — too low is quiet, too high clips):

```fish
# 50+ positive "hey clank" clips — vary distance, volume, cadence, who's speaking
.venv/bin/python scripts/train_wakeword/record_samples.py --label positive --count 50

# 30 hard negatives — talk, TV, similar words, but NEVER the wake word
.venv/bin/python scripts/train_wakeword/record_samples.py --label negative --count 30 --seconds 3
```

Clips land in `data/wakeword/positive/` and `data/wakeword/negative/`
(gitignored — they're personal audio, see below). More variety > more clips.

### 3. Generate synthetic positives (Piper)

The bulk of positive training data is synthetic speech across many voices:

```fish
git clone https://github.com/rhasspy/piper-sample-generator ~/oww-training/piper-sample-generator
# follow its README to fetch a generator voice, then:
python ~/oww-training/piper-sample-generator/generate_samples.py "hey clank" \
    --max-samples 2000 --output-dir ~/oww-training/synthetic_positive
```

### 4. Get the negative / background feature sets

The trainer mixes in large precomputed negative and room-impulse sets (AudioSet,
FMA, RIRs). The training notebook downloads these from Hugging Face — follow its
"data" cells. This is the multi-GB disk cost.

### 5. Train

Run the openWakeWord trainer (the notebook, or its `train.py` equivalent),
pointing it at:
- synthetic positives (step 3) **+** your real positives (`data/wakeword/positive/`),
- your hard negatives (`data/wakeword/negative/`) plus the downloaded negatives,
- export format: **ONNX** (Clank uses onnxruntime; you don't need the tflite export).

Output is a new `hey_clank.onnx`.

### 6. Audit the model (mandatory)

```fish
python scripts/train_wakeword/audit_onnx.py ~/oww-training/output/hey_clank.onnx
```

It hard-fails on custom operator domains, external-data tensors, or embedded
URLs/paths, and confirms it loads under stock onnxruntime CPU. On success it
prints the exact SHA256 line to pin. **If it fails, do not ship the model.**

### 7. Pin and install

1. Copy the line the audit printed into `_KNOWN_OWW_SHA256` in
   `src/voicecommand/voice_LED_control.py`, replacing the old `hey_clank.onnx`
   entry (update the dated audit comment above it).
2. Put the model in place:
   ```fish
   cp ~/oww-training/output/hey_clank.onnx models/wakeword/hey_clank.onnx
   ```
3. Restart Clank. At startup the loader re-hashes the file and refuses to run if
   it doesn't match the pin — so a typo here fails loudly, by design.

### 8. Verify recall

```fish
./start_clank.sh --oww-debug
```

`--oww-debug` logs the peak wake score each second. Say "hey clank" from across
the room a dozen times; you want consistent peaks well above the
`oww_threshold` (currently **0.15** in `config/default.yaml`). If real hits now
sit at 0.5–0.9 on the built-in mic, the retrain worked. Raise the threshold back
toward 0.3–0.5 if you start getting false triggers.

---

## A note on the recorded clips & privacy

`data/wakeword/` is gitignored — those are recordings of your voice and room and
shouldn't be committed. Only the trained, audited `hey_clank.onnx` ships in the
repo. (This matches Clank's runtime stance: live audio is RAM-only and never
written to disk; these training clips are the one deliberate exception, kept
local.)

---

## Quick option: custom verifier (does NOT drop into Clank as-is)

openWakeWord can train a lightweight per-speaker *verifier* on a base model from
just a handful of clips (`openwakeword.train_custom_verifier(...)`, see the
[upstream docs](https://github.com/dscripka/openWakeWord/blob/main/docs/custom_verifier_models.md)).
It outputs a `.pkl` that gates an existing wake model's detections. Clank's
loader (`WakeWordDetector`) currently consumes a single `.onnx` and has no
verifier hook, so using this would mean a small code change to load and apply the
verifier alongside the base model. Noted for completeness; the full retrain above
is the supported path.
