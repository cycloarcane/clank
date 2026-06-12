# Clank – Voice-controlled RGB LED assistant

Clank listens for spoken commands, transcribes them locally with the **Moonshine** speech-to-text model, parses the intent with a local **Ollama** LLM, and drives an **RGB LED strip** on an **ESP32** by publishing to a local **MQTT** broker.

Everything runs on your own hardware — no cloud APIs, no external data sent anywhere.

<!-- Demo video — upload Screencast_20241123_181801.webm as a GitHub issue/PR attachment and paste the URL here -->

---

## ⚠️ Disclaimer

Clank is a hobby project provided **as-is, with no warranty** of any kind. You run it entirely at your own risk. Please understand the following before using it:

- **Always-on microphone.** To detect its wake word, Clank continuously captures and transcribes audio from your microphone. Audio and transcripts are processed **locally, in memory, and discarded** — by default nothing is sent to the cloud and raw transcripts are not written to disk (only resolved commands are logged; see `security.log_transcripts`). Even so, you are running a device that is always listening.
- **Other people's privacy.** Recording or transcribing people without their knowledge or consent may be illegal where you live (one-/two-party consent laws vary by jurisdiction). If others share the space, inform them. Compliance is **your responsibility**.
- **Mains electricity is dangerous.** This project now drives a low-voltage (5/12 V) RGB LED strip. If you adapt it to switch 230/240 V (or 120 V) loads, doing so incorrectly can cause **electric shock, fire, or death**. Use only properly rated, fused, and enclosed hardware — or commercial smart plugs — and consult a qualified electrician for any fixed wiring. The authors accept **no liability** for damage, injury, or loss resulting from use of this project.
- **Not a safety device.** Do not use Clank to control anything where failure, a misheard command, or downtime could be hazardous (medical equipment, heating, security, etc.).

By using Clank you accept these terms.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Hardware requirements](#hardware-requirements)
3. [System requirements](#system-requirements)
4. [Step 1 — Clone and install Python dependencies](#step-1--clone-and-install-python-dependencies)
5. [Step 2 — Install and configure Ollama](#step-2--install-and-configure-ollama)
6. [Step 3 — Fetch the Moonshine models](#step-3--fetch-the-moonshine-models)
7. [Step 4 — Wire the RGB strip](#step-4--wire-the-rgb-strip)
8. [Step 5 — Set up the MQTT broker](#step-5--set-up-the-mqtt-broker)
9. [Step 6 — Flash and configure WLED](#step-6--flash-and-configure-wled)
10. [Step 7 — Run Clank](#step-7--run-clank)
11. [Voice commands](#voice-commands)
12. [Wake word](#wake-word)
13. [Configuration reference](#configuration-reference)
14. [Logs and monitoring](#logs-and-monitoring)
15. [Security features](#security-features)
16. [Model provenance and supply-chain hardening](#model-provenance-and-supply-chain-hardening)
17. [Auditing the model with Netron](#auditing-the-model-with-netron)
18. [Troubleshooting](#troubleshooting)
19. [Repository layout](#repository-layout)
20. [License](#license)

---

## How it works

```
Microphone ─► Silero VAD ─► Moonshine STT ─► wake-word gate ─► Ollama LLM ─► MQTT publish
                                                                                  │
                                                                          mosquitto broker
                                                                                  │
                                                                 ESP32 (WLED) ◄── wled/clank/api
                                                                      │
                                                                  RGB LED strip
```

1. **Voice activity detection** (Silero VAD) watches the microphone and fires when speech starts and ends.
2. **Transcription** (Moonshine ONNX, local) converts the audio to text.
3. **Wake-word gate** — utterances that don't contain the wake word **"clank"** are discarded immediately: no LLM call, no logging, nothing retained.
4. **Intent parsing** (Ollama, local) maps the command to a structured JSON object describing a colour, brightness, effect, and/or on-off state.
5. **Dispatch** — Clank translates that to a [WLED JSON state object](https://kno.wled.ge/interfaces/json-api/) and publishes it to the MQTT topic `wled/clank/api`. The ESP32 runs **[WLED](https://kno.wled.ge/)** (configured for an analogue/PWM strip), subscribes to that topic, and applies the change.

Clank and the broker run on the **same PC**; the ESP32 connects to the broker over WiFi. The two never talk directly — there is no device IP to configure on the Clank side. Running WLED also gives you its web UI, presets, and time-based effects for free.

---

## Hardware requirements

- **ESP32** development board (any variant with WiFi — ESP32-DevKitC, WROOM, etc.)
- An **RGB LED strip** (common-cathode / "common-ground" analogue strip — *not* addressable WS2812)
- **3 × NPN transistors** (e.g. 2N2222, BC337, or a logic-level N-MOSFET) to switch each colour channel, plus base resistors
- A suitable power supply for the strip (5 V or 12 V depending on your strip)
- A microphone accessible to your host machine (USB or built-in)

### Wiring

Each colour channel is low-side switched by a transistor: the ESP32 GPIO drives the **base/gate**, the strip's colour pin goes to the **collector/drain**, and the **emitter/source** goes to ground (shared with the strip's supply ground). Driving is **active-high** — a higher PWM duty = brighter.

| Channel | ESP32 GPIO |
|---|---|
| Red   | **GPIO 13** |
| Green | **GPIO 12** |
| Blue  | **GPIO 33** |

The pins are assigned in WLED's *Config → LED Preferences* (see [Step 6](#step-6--flash-and-configure-wled)). Pick output-capable GPIOs and avoid the strapping/flash pins (6–11, and ideally 0/2/15); if a colour comes out wrong, the channel order in WLED is swapped.

> A pinout reference image for the dev board is included in the repo root if you need it.

---

## System requirements

| Requirement | Notes |
|---|---|
| Python 3.10+ | 3.12+ tested |
| ~2 GB RAM | Moonshine base model |
| ~250 MB disk | ONNX model weights |
| Linux / macOS | Windows not tested |
| Ollama | Local LLM server |
| mosquitto | Local MQTT broker |
| Chrome or Edge browser | For flashing WLED via install.wled.me (Web Serial) |

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
3. Pull the recommended model:
   ```bash
   ollama pull qwen3:4b
   ```
   The intent-parsing task is simple (one short sentence → a fixed JSON schema), so a small model is plenty. `qwen3:4b` (~2.5 GB at Q4) fits comfortably on a **4 GB GPU**, which is the recommended default.

   **Choosing a Qwen3 model for your hardware:**

   | GPU VRAM | Suggested model | Approx. size |
   |---|---|---|
   | ~4 GB | `qwen3:4b` | ~2.5 GB |
   | ≤2 GB / CPU-only | `qwen3:1.7b` | ~1.4 GB |
   | 12 GB+ | `qwen3:14b` (higher accuracy) | ~9 GB |

   Any model that reliably outputs clean JSON works. **`qwen3:14b` will not fit in 4 GB of VRAM** — only choose it if you have a larger GPU.

3. **(Recommended for a dedicated box) Keep the model loaded for instant responses.**

   By default Ollama evicts the model from (V)RAM after ~5 minutes idle, so the
   first command after a pause is slow while it reloads. To keep it resident,
   set `OLLAMA_KEEP_ALIVE=-1` on the Ollama service. The installer offers to do
   this for you; to set it by hand on a systemd system:

   ```bash
   sudo systemctl edit ollama
   ```
   Add:
   ```ini
   [Service]
   Environment="OLLAMA_KEEP_ALIVE=-1"
   ```
   then `sudo systemctl restart ollama` and verify with `ollama ps` (the
   **UNTIL** column reads *Forever*). This only holds VRAM while idle — there's
   no compute and no GPU wear. Use a duration like `30m` instead of `-1` if you
   also use the GPU for other things and want it freed after you stop talking.

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

## Step 4 — Wire the RGB strip

Wire the strip to the ESP32 through the three transistors as described in [Hardware requirements](#wiring): **R → GPIO 13, G → GPIO 12, B → GPIO 33**, common ground shared with the strip's power supply. Power the strip from its own supply (not the ESP32's 3.3 V/5 V pin) — the GPIOs only drive the transistor bases, not the LED current.

---

## Step 5 — Set up the MQTT broker

Clank and the ESP32 communicate through a local [mosquitto](https://mosquitto.org/) broker running on your PC.

### Credentials

Broker credentials live in the gitignored `ESP32LEDs/secrets.h` (the single source of truth shared by the firmware, the broker setup script, and Clank). Copy the template and fill it in:

```bash
cp ESP32LEDs/secrets.h.example ESP32LEDs/secrets.h
# generate a broker password:
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
# then edit ESP32LEDs/secrets.h:
#   WIFI_SSID / WIFI_PASSWORD   – the WiFi the ESP32 joins
#   MQTT_BROKER                 – the PC's IP on that network (broker address)
#   MQTT_USER / MQTT_PASS       – broker login (user is "clank" by default)
```

> `MQTT_BROKER` is the PC running mosquitto. If the PC is a NetworkManager "shared" hotspot, it's the gateway `10.42.0.1`; on a home LAN, use the PC's LAN IP.

### Install and start mosquitto

A helper script installs and configures the broker. It reads the username/password from `secrets.h`, writes a config that listens on port **1883** with anonymous access **disabled**, and enables the service:

```bash
sudo bash scripts/setup_mosquitto.sh
```

(Currently targets Arch/pacman for the install step; on other distros install `mosquitto` with your package manager first, then re-run the script to do the config.)

### Firewall

If your PC runs a firewall, allow the ESP32's subnet to reach port 1883. For example, for a hotspot on `10.42.0.0/24` with `ufw`:

```bash
sudo ufw allow from 10.42.0.0/24 to any port 1883 proto tcp comment 'clank mqtt'
```

### Sync credentials to Clank

Clank reads the broker login from `.env` (see [Step 7](#step-7--run-clank)); set `MQTT_USER`/`MQTT_PASS` there to the same values.

---

## Step 6 — Flash and configure WLED

Clank drives the strip through [WLED](https://kno.wled.ge/), so the ESP32 runs WLED rather than a custom sketch. WLED handles the PWM, gives you a web UI and presets, and — crucially — provides the time-based **effects** Clank can trigger by voice.

### 6a — Flash WLED

1. Plug the ESP32 into this PC over USB and open **[install.wled.me](https://install.wled.me)** in **Chrome or Edge** (Web Serial is required; Firefox won't work).
2. Click **Install**, pick the latest stable release, select the serial port (e.g. `/dev/ttyUSB0`) and let it flash.
   > If it reports *"Serial port is not ready"*, another program holds the port — close other serial monitors/Arduino IDE, and close any stale install.wled.me tab (the browser keeps the port open). On Linux you may need to be in the `dialout` group.
3. When prompted, **Connect to Wi-Fi** and join the same `clank-net` hotspot the broker lives on (see [Step 5](#step-5--set-up-the-mqtt-broker)). The board reboots onto the hotspot.

### 6b — Point WLED at the strip and the broker

Find the device's IP from your hotspot's DHCP leases (e.g. `ip neigh show dev wlan0 | grep 10.42`), then either use the web UI or push the config over HTTP. Web UI route:

1. Open `http://<wled-ip>/` → **Config → LED Preferences**.
2. Add an output of type **Analog (PWM) RGB**, length **1**, with the three GPIOs **in R, G, B order**: `13, 12, 33`. Save (the board reboots).
3. **Config → Sync Interfaces → MQTT:** enable it, set **Broker** `10.42.0.1`, **Port** `1883`, your **Username/Password** (the `MQTT_USER`/`MQTT_PASS` from `secrets.h`), and **Device Topic** `wled/clank`. Save.

Or do both in one shot via the JSON config API (replace the password):
```bash
curl -X POST http://<wled-ip>/json/cfg -H 'Content-Type: application/json' -d '{
  "hw":{"led":{"total":1,"ins":[{"start":0,"len":1,"pin":[13,12,33],"type":43}]}},
  "if":{"mqtt":{"en":true,"broker":"10.42.0.1","port":1883,
    "user":"clank","psk":"your-broker-password","rtn":true,
    "topics":{"device":"wled/clank","group":"wled/all"}}}
}'
```
LED type `43` is WLED's 3-channel analog (RGB) bus. A single virtual pixel (`len:1`) is what makes the whole strip animate together — the right behaviour for an analogue strip.

Verify the strip responds before moving on:
```bash
curl 'http://<wled-ip>/win&A=255&R=255&G=0&B=0'   # full red
```
If red lights a different colour, your R/G/B pin order is swapped — fix it in LED Preferences.

> **Legacy alternative:** a minimal custom MQTT/PWM sketch (no effects) still lives in `ESP32LEDs/` if you'd rather not run WLED. It subscribes to `clank/rgb/set` with `{state,r,g,b,brightness}`; you'd set `mqtt.rgb_set_topic` back to that and flash it with the Arduino IDE / arduino-cli.

---

## Step 7 — Run Clank

Clank reads configuration from `.env` (loaded automatically by `start_clank.sh`). Create it (never commit this file):

```bash
cat > .env <<'EOF'
MQTT_USER=clank
MQTT_PASS=your-broker-password
CLANK_LLM_MODEL=qwen3:4b
EOF
```

Then start:
```bash
./start_clank.sh
```

Clank prints `Listening. Press Ctrl+C to quit.` when ready. You should also see:
```
MQTT RGB controller -> 127.0.0.1:1883 topic 'wled/clank/api'
```

> **Tip:** if the strip seems to fire on background noise, your mic gain is too high — lower the input volume or raise `audio.vad_threshold`.

### Quick test without a microphone

You can drive the strip directly to confirm the broker → ESP32 path before testing voice:
```bash
mosquitto_pub -h 127.0.0.1 -u clank -P 'your-broker-password' \
  -t wled/clank/api -m '{"on":true,"bri":180,"seg":[{"col":[[255,0,0]]}]}'
```

---

## Voice commands

Say the wake word **"clank"**, then a command. Clank controls one RGB strip — colour, brightness, on/off, and time-based effects:

| What you say | What happens |
|---|---|
| "clank, turn the lights on" | Strip on (last colour) |
| "clank, turn off the lights" | Strip off |
| "clank, make it red" | Strip red |
| "clank, set the strip to blue" | Strip blue |
| "clank, warm white at half brightness" | Warm white, 50% |
| "clank, dim to 20 percent" | Brightness 20% |
| "clank, make the lights breathe" | Breathe effect |
| "clank, cycle through colours" | Colorloop effect |
| "clank, candle mode in orange" | Candle flicker, orange |
| "clank, strobe the lights" | Strobe effect |
| "clank, make the strobe quicker" | Speed up the running effect |
| "clank, make the effect more intense" | Raise effect intensity |
| "clank, stop the effect" | Back to solid colour |

Setting a colour, brightness, effect, speed, or intensity implies the strip turns on. Anything not about the light strip is discarded.

**Recognised colours:** red, green, blue, white, warm white, yellow, orange, amber, purple, violet, pink, magenta, cyan, teal, turquoise, lime, gold. (Defined in `src/voicecommand/validation.py` → `COLOR_RGB`.)

**Recognised effects:** solid, blink, breathe, fade, saw, sine, heartbeat, random, dynamic, colorloop, rainbow, strobe, strobe rainbow, strobe mega, blink rainbow, lightning, candle, fire (plus spoken synonyms). These are limited to effects that animate the *whole* strip over time — spatial effects (wipe, chase, sparkle, comet…) need addressable pixels and aren't meaningful on an analogue strip, so they're deliberately excluded. (Mapped to WLED effect IDs in `validation.py` → `WLED_EFFECTS`.)

**Effect speed & intensity:** say "faster"/"quicker"/"slower" to change how fast the active effect animates, or "more/less intense" for its strength — e.g. *"make the strobe quicker"*. These map to WLED's per-segment `sx`/`ix` and adjust whatever effect is already running without restarting it.

### MQTT payload format

Clank publishes [WLED JSON state objects](https://kno.wled.ge/interfaces/json-api/) to `wled/clank/api`. Colour and effect go in the segment; on/off and brightness are top-level. For example "candle mode in orange" becomes:
```json
{ "on": true, "seg": [ { "col": [[255, 80, 0]], "fx": 88 } ] }
```
WLED also publishes its own state on `wled/clank/...` and supports the full JSON API, so you can build presets and richer automations on top.

---

## Wake word

Clank only acts on speech that contains the wake word. There are two engines, selected by `audio.wake_engine`:

- **`text`** (default) — every utterance is transcribed, then the word **"clank"** is matched in the transcript (fuzzy, so mishearings like "clink"/"crank" still trigger). Simple and reliable; speech-to-text runs continuously.
- **`openwakeword`** (experimental) — a small acoustic model detects the wake word from the raw audio *before* transcription, so Moonshine stays idle until you speak the wake word (lower CPU, stronger privacy). Requires a wake-word model; the bundled ones are SHA256-pinned and integrity-checked at load. A custom **"hey clank"** model is being trained but is not enabled by default.

Stick with `text` unless you have a tuned acoustic model.

---

## Configuration reference

All settings live in `config/default.yaml`; secrets and a few overrides come from environment variables (via `.env`).

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `MQTT_USER` | `clank` | MQTT broker username |
| `MQTT_PASS` | *(none)* | MQTT broker password (must match the broker) |
| `CLANK_LLM_MODEL` | `qwen3:4b` | Ollama model name |
| `CLANK_LLM_ENDPOINT` | `http://127.0.0.1:11434/api/generate` | Ollama API endpoint |
| `CLANK_CONFIG` | `config/default.yaml` | Path to config file |
| `CLANK_LOG_LEVEL` | `INFO` | Log level (DEBUG / INFO / WARNING / ERROR) |

### config/default.yaml (key sections)

```yaml
audio:
  sampling_rate: 16000
  vad_threshold: 0.5          # 0.0–1.0, raise to reduce false triggers
  min_silence_duration_ms: 300
  max_speech_seconds: 15
  wake_word: "clank"
  require_wake_word: true
  wake_engine: "text"         # "text" or "openwakeword"

mqtt:
  broker_host: "127.0.0.1"    # Clank → broker (same PC)
  broker_port: 1883
  rgb_set_topic: "wled/clank/api"   # WLED JSON API topic (<device>/api)

llm:
  model: "qwen3:4b"
  temperature: 0.0
  max_tokens: 150
  timeout: 90.0
  response_format: "json"     # force a single valid JSON object
  think: false                # disable qwen3 "thinking" (set null for non-reasoning models)

security:
  log_transcripts: false      # keep raw speech ephemeral; true only for debugging
  enable_audit_logging: true
```

---

## Logs and monitoring

| File | Contents |
|---|---|
| `logs/clank.log` | Application activity, rotating, 10 MB max |
| `logs/audit.log` | Security events in JSON format |

```bash
tail -f logs/clank.log                 # follow application log
tail -f logs/audit.log | jq '.'        # watch security events (needs jq)
```

By default only resolved commands are logged (e.g. `Command(rgb): {'color': 'red'}`), never raw transcripts. Sensitive fields are redacted in `clank.log`.

You can also watch the live MQTT traffic:
```bash
mosquitto_sub -h 127.0.0.1 -u clank -P 'your-broker-password' -t 'clank/#' -v
```

---

## Security features

| Feature | Detail |
|---|---|
| **Local-only** | STT, LLM, and the broker all run on your machine; no data leaves it at runtime |
| **Ephemeral speech** | Non-command utterances are discarded at the wake-word gate; raw transcripts are never persisted unless `log_transcripts` is enabled |
| **Model integrity** | Moonshine weights are SHA256-verified before load; openWakeWord models are hash-pinned and integrity-checked |
| **Commit-locked downloads** | Moonshine weights pinned to audited commit `2501abf` |
| **Input validation** | Transcribed text is sanitised and length-bounded before reaching the LLM prompt |
| **LLM response validation** | JSON output is checked against an allowlist of actions, colours, and states before dispatch |
| **MQTT authentication** | The broker requires a username/password; anonymous access is disabled |
| **Scoped firewall** | Recommended `ufw` rule limits broker access to the local device subnet |
| **Structured audit logging** | Security events written to a separate JSON log with automatic redaction |

> **Note:** MQTT on port 1883 is unencrypted. On an isolated hotspot this is acceptable; for a shared LAN consider enabling MQTT over TLS (port 8883) on both the broker and firmware.

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

## Troubleshooting

**"No module named 'sounddevice'"**
```bash
sudo apt-get install portaudio19-dev   # Linux
brew install portaudio                  # macOS
pip install sounddevice
```

**Clank doesn't react to my voice**
- Check the mic is the one Python uses: `python3 -c "import sounddevice as sd; print(sd.query_devices())"` and confirm the default input is your mic (not muted).
- Remember you must say the wake word **"clank"** first; non-wake speech is silently discarded.
- If it triggers on noise instead, your mic gain is too high — lower it or raise `audio.vad_threshold`.

**ESP32 serial shows `failed (rc=-2)` (MQTT)**
- The broker isn't reachable. Confirm `mosquitto` is running (`systemctl is-active mosquitto`), the firewall allows the ESP32's subnet on 1883, and `MQTT_BROKER` in `secrets.h` is the PC's address on the ESP32's network.

**WLED connects but the strip doesn't light / wrong colours**
- Verify the transistor wiring and that the strip has its own power and shared ground.
- If "red" shows as another colour, the channel order is swapped — fix the R/G/B pin order in WLED's *Config → LED Preferences*.
- Confirm WLED's MQTT is enabled and pointed at the broker (*Config → Sync Interfaces → MQTT*); the strip should react to a manual `mosquitto_pub` to `wled/clank/api`.

**"SHA256 mismatch" on startup**
Re-run `./scripts/fetch_moonshine.sh` and verify with `sha256sum -c SHA256SUMS`.

**Ollama connection refused**
```bash
ollama serve   # start the server
ollama list    # confirm your model is pulled
```

**WLED isn't reachable after flashing**
- It only joins WiFi once you complete the **Connect to Wi-Fi** step in the installer. If you skipped it, the board falls back to its own `WLED-AP` (password `wled1234`) — join that from a phone and set the WiFi there.
- Find its address from the hotspot leases: `ip neigh show dev wlan0 | grep 10.42`.

---

## Repository layout

```
clank/
├── README.md                    ← this file
├── LICENSE
├── requirements.txt             ← Python dependencies
├── SHA256SUMS                   ← model digests
├── start_clank.sh               ← startup script (loads .env, activates venv)
│
├── config/
│   ├── default.yaml             ← all tunable settings (audio, mqtt, llm)
│   └── devices.yaml             ← device registry: strips + plugs by spoken name
│
├── logs/                        ← application and audit logs (gitignored)
├── models/
│   ├── moonshine/               ← ONNX weights (fetched by fetch_moonshine.sh)
│   │   ├── encoder_model.onnx
│   │   └── decoder_model_merged.onnx
│   └── wakeword/hey_clank.onnx  ← custom wake-word model (SHA256-pinned)
│
├── scripts/
│   ├── fetch_moonshine.sh       ← downloads pinned, verified model weights
│   ├── setup_mosquitto.sh       ← installs/configures the MQTT broker
│   └── plug_jukebox.py          ← play a rhythm on the smart plugs (for fun)
│
├── src/
│   ├── assets/
│   │   └── tokenizer.json       ← Moonshine subword tokenizer
│   └── voicecommand/
│       ├── voice_LED_control.py ← main app: VAD → STT → wake gate → LLM → MQTT
│       ├── onnx_model.py        ← SHA256-verified Moonshine loader
│       ├── config.py            ← typed config with env-var overrides
│       ├── devices.py           ← device registry (resolve target, build prompt)
│       ├── validation.py        ← input/output sanitisation; set_rgb + set_switch
│       └── secure_logging.py    ← rotating logs and audit log with redaction
│
└── ESP32LEDs/                   ← legacy custom firmware (no effects); WLED is the default
    ├── ESP32LEDs.ino            ← minimal MQTT RGB strip via PWM + NPN
    ├── secrets.h.example        ← template for WiFi + MQTT creds (copy to secrets.h)
    └── secrets.h                ← your WiFi + MQTT creds (gitignored)
```

---

## License

MIT — see `LICENSE` for full text.
