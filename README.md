# Clank – Voice‑controlled LED assistant

Clank turns spoken commands into JSON actions for LED strips (and whatever hardware you wire up next).  
It relies on the **Moonshine** speech‑to‑text model, **Ollama** for intent parsing, and ESP32 firmware for the LEDs.

---

[Screencast_20241123_181801.webm](https://github.com/user-attachments/assets/dec3e33a-f05d-4ce7-9d4b-73716c0f2577)


## Prerequisites

- **Ollama** installed and running: `ollama serve`
- A model pulled: `ollama pull qwen3:14b` (or your preferred model)
- **ESP32** with LED firmware running on your network

## Quick‑start

```bash
# clone and enter
git clone https://github.com/cycloarcane/clank.git
cd clank

# create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# install Python dependencies
pip install -r requirements.txt

# fetch the vetted ONNX weights (≈250 MB) and generate SHA256SUMS
./scripts/fetch_moonshine.sh

# verify integrity
sha256sum --quiet -c SHA256SUMS   # prints "OK" twice

# configure your setup (edit src/voicecommand/voice_LED_control.py):
# - Update ESP32_IP to your ESP32's IP address  
# - Update LLM_MODEL to your preferred Ollama model

# fire it up
python3 src/voicecommand/voice_LED_control.py
```

---

## Repository layout

```text
clank/
├─ README.md               ← *this file*
├─ requirements.txt        ← Python dependencies
├─ SHA256SUMS              ← model digests you can re‑check anytime
├─ scripts/
│   └─ fetch_moonshine.sh  ← downloads the exact weights we audited
├─ models/
│   └─ moonshine/
│       ├─ encoder_model.onnx
│       └─ decoder_model_merged.onnx
├─ src/                    ← Python backend
│   ├─ assets/
│   │   └─ tokenizer.json  ← Moonshine tokenizer
│   └─ voicecommand/
│       ├─ voice_LED_control.py ← main application
│       └─ onnx_model.py   ← security-hardened model wrapper
└─ ESP32LEDs/              ← micro‑controller firmware
```

---

## Security Features

Clank implements multiple layers of security for the AI models:

- **Commit-locked downloads**: Only the audited `2501abf` commit is downloaded
- **SHA256 verification**: All models are integrity-checked before loading  
- **No runtime downloads**: The application only uses pre-verified local models
- **Official library integration**: Uses UsefulSensors' official moonshine-onnx library with local model loading

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
