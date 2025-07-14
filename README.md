# Clank – Voice‑controlled LED assistant

Clank turns spoken commands into JSON actions for LED strips (and whatever hardware you wire up next).  
It relies on the **Moonshine** speech‑to‑text model, an LLM for intent parsing, and ESP32 firmware for the LEDs.

---

[Screencast_20241123_181801.webm](https://github.com/user-attachments/assets/dec3e33a-f05d-4ce7-9d4b-73716c0f2577)


## Quick‑start

```bash
# clone and enter
git clone https://github.com/cycloarcane/clank.git
cd clank

# Python deps (better: use a venv)
pip install -r requirements.txt

# fetch the vetted ONNX weights (≈250 MB) and generate SHA256SUMS
./scripts/fetch_moonshine.sh

# verify integrity
sha256sum --quiet -c SHA256SUMS   # prints “OK” twice

# fire it up
python -m src.voice_led_control
```

---

## Repository layout

```text
clank/
├─ README.md               ← *this file*
├─ SHA256SUMS              ← model digests you can re‑check anytime
├─ scripts/
│   └─ fetch_moonshine.sh  ← downloads the exact weights we audited
├─ models/
│   └─ moonshine/
│       ├─ encoder_model.onnx
│       └─ decoder_model_merged.onnx
├─ src/                    ← Python backend
│   ├─ voice_led_control.py
│   ├─ onnx_model.py
│   └─ …
└─ ESP32LEDs/              ← micro‑controller firmware
```

---

## Model provenance & supply‑chain hardening

| Item | Value |
|------|-------|
| **Repository** | `UsefulSensors/moonshine` on Hugging Face |
| **Immutable commit** | `2501abf` |
| **Files** | `onnx/merged/base/float/encoder_model.onnx` (80 MB)  <br> `onnx/merged/base/float/decoder_model_merged.onnx` (166 MB) |
| **Download script** | `scripts/fetch_moonshine.sh` |
| **Hash file** | `SHA256SUMS` (Your own SHA256 sum can be found in the model directory after running the fetch_moonshine.sh script) |

### Why commit‑lock?

Using `…/resolve/**2501abf**/…` guarantees every clone receives *identical bytes*.  
A silent upstream update can only occur if we *change the commit hash and publish new checksums*.

---

## Auditing the model with Netron

We visually inspected the weights for PAIT‑ONNX‑200 class architectural back‑doors:

```bash
pip install netron            # one‑time
netron models/moonshine/encoder_model.onnx &   # opens http://localhost:8080
netron models/moonshine/decoder_model_merged.onnx &
```

1. **View → Layout → Hierarchical** for a tall vertical graph.  
2. **Search** (`Ctrl/⌘‑F`) for operators that don’t belong in an acoustic model: `If`, `Where`, `Equal`, `ArgMax`, tiny `MatMul` with a constant.  
3. Legitimate paths are hundreds of Conv / GRU blocks. A back‑door path is usually < 20 nodes and rejoins just before `Softmax`.  
4. Repeat this check whenever you upgrade the weights.

We found **no suspicious parallel branches** in commit `2501abf`; the hashes in *SHA256SUMS* reflect this vetted state.

---

## Re‑auditing & updating

1. Checkout a new branch.  
2. Update `MOON_COMMIT` inside `scripts/fetch_moonshine.sh`.  
3. Run the script, inspect the graphs in Netron, update `SHA256SUMS` (`sha256sum … > SHA256SUMS`).  
4. Open a PR summarising what you checked (Netron screenshots welcome).  
5. Once merged, downstream users repeat the standard quick‑start and stay safe.

---

## License

MIT (see `LICENSE` for full text)
