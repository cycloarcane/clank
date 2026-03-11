# Clank – Voice-controlled LED assistant

Clank listens for spoken commands, transcribes them locally with the **Moonshine** speech-to-text model, parses the intent with a local **Ollama** LLM, and sends LED control commands to an **ESP32** microcontroller over your LAN.

Everything runs on your own hardware — no cloud APIs, no external data sent anywhere.

<!-- Demo video — upload Screencast_20241123_181801.webm as a GitHub issue/PR attachment and paste the URL here -->

---

## Table of contents

1. [How it works](#how-it-works)
2. [Hardware requirements](#hardware-requirements)
3. [System requirements](#system-requirements)
4. [Step 1 — Clone and install Python dependencies](#step-1--clone-and-install-python-dependencies)
5. [Step 2 — Install and configure Ollama](#step-2--install-and-configure-ollama)
6. [Step 3 — Fetch the Moonshine models](#step-3--fetch-the-moonshine-models)
7. [Step 4 — Flash the ESP32 firmware](#step-4--flash-the-esp32-firmware)
8. [Step 5 — Generate an API key](#step-5--generate-an-api-key)
9. [Step 6 — Run Clank](#step-6--run-clank)
10. [Voice commands](#voice-commands)
11. [Configuration reference](#configuration-reference)
12. [Device management](#device-management)
13. [Logs and monitoring](#logs-and-monitoring)
14. [Security features](#security-features)
15. [Model provenance and supply-chain hardening](#model-provenance-and-supply-chain-hardening)
16. [Auditing the model with Netron](#auditing-the-model-with-netron)
17. [Re-auditing and updating models](#re-auditing-and-updating-models)
18. [Troubleshooting](#troubleshooting)
19. [Repository layout](#repository-layout)
20. [License](#license)

---

## How it works

```
Microphone ──► Silero VAD ──► Moonshine STT ──► Ollama LLM ──► ESP32 /led-control
```

1. **Voice activity detection** (Silero VAD) watches the microphone and fires when speech starts and ends.
2. **Transcription** (Moonshine ONNX, local) converts the audio to text.
3. **Intent parsing** (Ollama, local) maps the text to a structured JSON LED command.
4. **Dispatch** — the validated JSON is POSTed to the ESP32 over HTTP with an API key header.

---

## Hardware requirements

- **ESP32** development board (any variant with WiFi — ESP32-DevKitC, WROOM, etc.)
- **LEDs** wired to GPIO 18 (red), 23 (green), 16 (blue) — adjust pins in the firmware if needed
- A microphone accessible to your host machine (USB or built-in)

---

## System requirements

| Requirement | Notes |
|---|---|
| Python 3.10+ | 3.12 recommended |
| ~2 GB RAM | Moonshine base model |
| ~250 MB disk | ONNX model weights |
| Linux / macOS | Windows not tested |
| Ollama | Local LLM server |
| Arduino IDE 2.x **or** arduino-cli | For flashing the ESP32 |

**System audio libraries (Linux):**
```bash
sudo apt-get install libsndfile1 portaudio19-dev python3-venv
```

**System audio libraries (macOS):**
```bash
brew install portaudio
```

---

## Step 1 — Clone and install Python dependencies

```bash
git clone https://github.com/cycloarcane/clank.git
cd clank

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

---

## Step 2 — Install and configure Ollama

1. Download and install Ollama from [ollama.com](https://ollama.com).
2. Start the server:
   ```bash
   ollama serve
   ```
3. Pull the recommended model (≈8 GB download):
   ```bash
   ollama pull qwen3:14b
   ```
   Any model that reliably outputs clean JSON works. Smaller models like `qwen3:4b` or `llama3.2:3b` run faster on modest hardware.

---

## Step 3 — Fetch the Moonshine models

The script downloads weights pinned to a specific audited commit and writes `SHA256SUMS`:

```bash
./scripts/fetch_moonshine.sh
```

Verify integrity:
```bash
sha256sum -c SHA256SUMS    # both lines should print OK
```

**Do not skip the verification step.** If the hashes do not match, do not run Clank — re-run the fetch script and investigate.

---

## Step 4 — Flash the ESP32 firmware

The firmware lives at `ESP32LEDs/ESP32LEDs.ino`. Before flashing, open the file and fill in three values:

```cpp
const char* ssid     = "YourWiFiNetwork";
const char* password = "YourWiFiPassword";
const char* API_KEY  = "";   // fill in after Step 5
```

Leave `API_KEY` empty for now — you will generate it in Step 5 and re-flash (or update via serial monitor).

### Option A — Arduino IDE 2.x

1. **Install Arduino IDE 2.x** from [arduino.cc/en/software](https://www.arduino.cc/en/software).

2. **Add the ESP32 board package.**
   Open *File → Preferences*, find *Additional boards manager URLs*, and add:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```

3. **Install the ESP32 core.**
   Open *Tools → Board → Boards Manager*, search for `esp32` by Espressif, and click **Install**.

4. **Install the ArduinoJson library.**
   Open *Sketch → Include Library → Manage Libraries*, search for `ArduinoJson` by Benoit Blanchon, and click **Install** (version 6.x).
   > `WiFi`, `WebServer`, and `ESPmDNS` are included with the ESP32 core — no separate install needed.

5. **Open the sketch.**
   *File → Open* → navigate to `ESP32LEDs/ESP32LEDs.ino`.

6. **Select your board and port.**
   - *Tools → Board → esp32 → ESP32 Dev Module* (or whichever matches your hardware)
   - *Tools → Port* → select the port your ESP32 is on (e.g. `/dev/ttyUSB0`, `/dev/ttyACM0`, or `COM3`)

7. **Upload.**
   Click the **→ Upload** button. The IDE compiles and flashes. When done, open *Tools → Serial Monitor* at 115200 baud — you should see the WiFi connection and IP address printed.

### Option B — arduino-cli (command line)

1. **Install arduino-cli.**
   ```bash
   # Linux / macOS (official install script)
   curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
   # then add the installed binary to your PATH, e.g.:
   export PATH="$HOME/bin:$PATH"
   ```

2. **Add the ESP32 board package URL and update the index.**
   ```bash
   arduino-cli config init
   arduino-cli config add board_manager.additional_urls \
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   arduino-cli core update-index
   ```

3. **Install the ESP32 core and ArduinoJson library.**
   ```bash
   arduino-cli core install esp32:esp32
   arduino-cli lib install "ArduinoJson"
   ```

4. **Find your ESP32's port.**
   ```bash
   arduino-cli board list
   # Look for a line with "Unknown" or "ESP32" — note the port (e.g. /dev/ttyUSB0)
   ```

5. **Compile and upload.**
   ```bash
   arduino-cli compile \
     --fqbn esp32:esp32:esp32 \
     ESP32LEDs/ESP32LEDs.ino

   arduino-cli upload \
     --fqbn esp32:esp32:esp32 \
     --port /dev/ttyUSB0 \
     ESP32LEDs/ESP32LEDs.ino
   ```
   Replace `/dev/ttyUSB0` with your actual port.

6. **Confirm the upload.**
   ```bash
   arduino-cli monitor --port /dev/ttyUSB0 --config baudrate=115200
   # Press Ctrl+C to exit the monitor
   ```
   You should see the device connect to WiFi and print its IP address.

### Note the ESP32's IP address

The IP is printed on the serial monitor each boot. You will need it in Step 6. If your router supports it, assign a static DHCP lease to the ESP32's MAC address so the IP never changes.

---

## Step 5 — Generate an API key

Generate a cryptographically random key:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Example output:
```
K3dRm9vXpQlTnYwZ8uBfA2sGcHeJiOkV1yMqCrNxDtL
```

**Flash the key into the ESP32** by setting `API_KEY` in `ESP32LEDs.ino` to this value and re-uploading (Steps 4.5–4.7 / 4.4–4.5 above).

Alternatively, register the device through Clank's device manager, which prints the ready-to-paste C++ line:
```bash
python3 register_device.py "Living-Room-LEDs"
# Prints: const char* API_KEY = "K3dRm9vX...";
```

---

## Step 6 — Run Clank

Set environment variables and start:

```bash
# Activate the virtual environment if not already active
source .venv/bin/activate

# Required: your ESP32's IP address
export ESP32_IP=192.168.0.18

# Required: the API key you generated in Step 5
export ESP32_API_KEY=K3dRm9vXpQlTnYwZ8uBfA2sGcHeJiOkV1yMqCrNxDtL

# Optional: change the Ollama model (default: qwen3:14b)
export LLM_MODEL=qwen3:14b

python3 src/voicecommand/voice_LED_control.py
```

Or use the startup script, which loads variables from a `.env` file automatically:
```bash
# Create a .env file (never commit this file)
cat > .env <<'EOF'
ESP32_IP=192.168.0.18
ESP32_API_KEY=your-key-here
LLM_MODEL=qwen3:14b
EOF

./start_clank.sh
```

Clank prints `Listening. Press Ctrl+C to quit.` when it is ready.

---

## Voice commands

Speak naturally. Clank responds to LED commands addressed to "Computer":

| What you say | What happens |
|---|---|
| "Computer, turn on the red LED" | Red LED on |
| "Computer, turn off the blue light" | Blue LED off |
| "Computer, set green LED to 50%" | Green LED at 50% brightness |
| "Computer, turn on all LEDs" | All three LEDs on |
| "Computer, turn off all lights" | All three LEDs off |

Anything that does not map to an LED command is logged and discarded.

---

## Configuration reference

All settings live in `config/default.yaml` and can be overridden by environment variables.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `ESP32_IP` | `192.168.0.18` | IP address of the ESP32 |
| `ESP32_API_KEY` | *(none)* | Shared API key for ESP32 authentication |
| `LLM_MODEL` | `qwen3:14b` | Ollama model name |
| `CLANK_CONFIG` | `config/default.yaml` | Path to config file |
| `CLANK_LLM_ENDPOINT` | `http://127.0.0.1:11434/api/generate` | Ollama API endpoint |
| `CLANK_LOG_LEVEL` | `INFO` | Log level (DEBUG / INFO / WARNING / ERROR) |
| `CLANK_HTTPS_CERT` | *(none)* | Path to TLS certificate for HTTPS |
| `CLANK_HTTPS_KEY` | *(none)* | Path to TLS private key for HTTPS |

### config/default.yaml (key sections)

```yaml
audio:
  sampling_rate: 16000
  vad_threshold: 0.5          # 0.0–1.0, raise to reduce false triggers
  min_silence_duration_ms: 300
  max_speech_seconds: 15

llm:
  model: "qwen3:14b"
  temperature: 0.0
  max_tokens: 150
  timeout: 30.0

network:
  use_service_discovery: true  # auto-discover ESP32 via mDNS
  connection_timeout: 10.0

security:
  max_requests_per_minute: 60
  enable_audit_logging: true
```

### Generating HTTPS certificates (optional)

If you want to encrypt traffic between Clank and the ESP32 (requires HTTPS support on the ESP32 side):
```bash
python3 scripts/generate_certs.py --hostname clank-led.local
export CLANK_HTTPS_CERT=certs/server.crt
export CLANK_HTTPS_KEY=certs/server.key
```

---

## Device management

Register a device and get the API key line ready for the firmware:
```bash
python3 register_device.py "Kitchen-LEDs"
# Device registered successfully!
# Device ID: device_abc123...
# API Key: K3dRm9vX...
# Add this to your ESP32 configuration:
# const char* API_KEY = "K3dRm9vX...";
```

List registered devices:
```python
python3 - <<'EOF'
from src.voicecommand.auth import AuthManager
auth = AuthManager()
for d in auth.list_devices():
    status = "active" if d.is_active else "revoked"
    print(f"{d.name} ({d.device_id}) — {status}")
EOF
```

---

## Logs and monitoring

| File | Contents |
|---|---|
| `logs/clank.log` | Application activity, rotating, 10 MB max |
| `logs/audit.log` | Security events in JSON format |

```bash
# Follow application log
tail -f logs/clank.log

# Watch security events (requires jq)
tail -f logs/audit.log | jq '.'

# Check for authentication failures
grep '"event_type": "auth_failure"' logs/audit.log
```

Sensitive fields (API keys, tokens, IP addresses) are automatically redacted in `clank.log`.

---

## Security features

| Feature | Detail |
|---|---|
| **Model integrity** | SHA256 hashes verified before any model is loaded |
| **Commit-locked downloads** | Weights pinned to audited commit `2501abf` |
| **No network calls at runtime** | All AI runs locally; no data leaves the machine |
| **Input validation** | Transcribed text is sanitised and length-bounded before reaching the LLM prompt, preventing prompt injection via crafted audio |
| **LLM response validation** | JSON output is checked against an allowlist of valid actions, colours, and states before dispatch |
| **ESP32 authentication** | `POST /led-control` requires a matching `X-API-Key` header; unauthenticated requests get 401 |
| **mDNS device discovery** | ESP32 advertises `_clank-led._tcp` so Clank finds it without hardcoded IPs |
| **Structured audit logging** | Security events written to a separate JSON log with automatic redaction |
| **Rate limiting** | 60 requests per minute per client IP |

---

## Model provenance and supply-chain hardening

| Item | Value |
|---|---|
| **Repository** | `UsefulSensors/moonshine` on Hugging Face |
| **Pinned commit** | `2501abf` |
| **Encoder** | `onnx/merged/base/float/encoder_model.onnx` (~80 MB) |
| **Decoder** | `onnx/merged/base/float/decoder_model_merged.onnx` (~166 MB) |
| **Download script** | `scripts/fetch_moonshine.sh` |
| **Hash file** | `SHA256SUMS` |

Using `…/resolve/2501abf/…` in the download URL guarantees every clone receives identical bytes. A silent upstream change can only reach users if we change the pinned commit and publish new checksums — intentional, reviewed, and auditable.

---

## Auditing the model with Netron

We visually inspected the weights for PAIT-ONNX-200 class architectural back-doors:

```bash
pip install netron
netron models/moonshine/encoder_model.onnx &
netron models/moonshine/decoder_model_merged.onnx &
# opens http://localhost:8080
```

1. **View → Layout → Hierarchical** for a tall vertical graph.
2. **Search** (`Ctrl+F`) for operators that do not belong in an acoustic model: `If`, `Where`, `Equal`, `ArgMax`, small `MatMul` with a constant input.
3. Legitimate paths are hundreds of Conv / GRU blocks. A back-door path is typically fewer than 20 nodes and rejoins just before `Softmax`.
4. Repeat whenever you update the weights.

We found **no suspicious parallel branches** in commit `2501abf`. The hashes in `SHA256SUMS` reflect this vetted state.

---

## Re-auditing and updating models

1. Create a new branch.
2. Update `MOON_COMMIT` inside `scripts/fetch_moonshine.sh`.
3. Run the script, inspect graphs in Netron, update `SHA256SUMS`:
   ```bash
   sha256sum models/moonshine/encoder_model.onnx \
             models/moonshine/decoder_model_merged.onnx > SHA256SUMS
   ```
4. Open a PR summarising what you checked (Netron screenshots welcome).
5. Once merged, users re-run the quick-start and stay safe.

---

## Troubleshooting

**"No module named 'sounddevice'"**
```bash
sudo apt-get install portaudio19-dev   # Linux
brew install portaudio                  # macOS
pip install sounddevice
```

**"SHA256 mismatch" on startup**
The model file is corrupt or was modified. Re-run `./scripts/fetch_moonshine.sh` and verify again with `sha256sum -c SHA256SUMS`.

**"Error sending command to ESP32" / connection refused**
- Confirm the ESP32 is powered and connected to WiFi (check serial monitor).
- Confirm `ESP32_IP` matches the address printed on the serial monitor.
- Check that `ESP32_API_KEY` matches `API_KEY` in the firmware exactly.

**ESP32 serial monitor shows nothing after flashing**
- Make sure the baud rate is set to **115200**.
- Press the **EN/RST** button on the ESP32 to trigger a reboot and print the startup output.

**"401 Authentication failed" in Clank logs**
The `ESP32_API_KEY` environment variable and the `API_KEY` constant in `ESP32LEDs.ino` do not match. Re-flash the firmware with the correct key.

**Ollama connection refused**
```bash
ollama serve   # start the server
ollama list    # confirm your model is pulled
```

**No devices found via mDNS discovery**
```bash
# Linux — check the ESP32 is advertising
avahi-browse -r _clank-led._tcp

# macOS
dns-sd -B _clank-led._tcp
```
If nothing appears, confirm `ESPmDNS` is included in the firmware and the ESP32 is on the same subnet.

**VAD triggers too easily on background noise**
Raise `vad_threshold` in `config/default.yaml` (e.g. from `0.5` to `0.7`).

---

## Repository layout

```
clank/
├── README.md                    ← this file
├── LICENSE
├── requirements.txt             ← Python dependencies
├── requirements-secure.txt      ← extended dependency list (for development)
├── SHA256SUMS                   ← model digests
├── install.sh                   ← one-command automated installer
├── start_clank.sh               ← startup script (loads .env, activates venv)
├── register_device.py           ← CLI helper to register an ESP32 and get its API key
│
├── config/
│   └── default.yaml             ← all tunable settings
│
├── certs/                       ← auto-generated TLS certificates (gitignored)
├── logs/                        ← application and audit logs (gitignored)
├── models/
│   └── moonshine/               ← ONNX weights (fetched by fetch_moonshine.sh)
│       ├── encoder_model.onnx
│       └── decoder_model_merged.onnx
│
├── scripts/
│   ├── fetch_moonshine.sh       ← downloads pinned, verified model weights
│   └── generate_certs.py        ← generates self-signed TLS certificates
│
├── src/
│   ├── assets/
│   │   └── tokenizer.json       ← Moonshine subword tokenizer
│   └── voicecommand/
│       ├── voice_LED_control.py         ← main application entry point
│       ├── voice_LED_control_secure.py  ← security framework stub (in progress)
│       ├── onnx_model.py                ← SHA256-verified model loader
│       ├── config.py                    ← typed config with env-var overrides
│       ├── validation.py                ← input/output sanitisation and allowlists
│       ├── auth.py                      ← device registration and API key management
│       ├── discovery.py                 ← mDNS auto-discovery of ESP32 devices
│       └── secure_logging.py            ← rotating logs and audit log with redaction
│
└── ESP32LEDs/
    └── ESP32LEDs.ino            ← ESP32 firmware (HTTP server, mDNS, auth)
```

---

## License

MIT — see `LICENSE` for full text.
