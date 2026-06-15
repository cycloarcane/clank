import argparse
import os
import sys
import time
import json
import difflib
import hashlib
import logging
import requests
from queue import Queue
import numpy as np
from silero_vad import VADIterator, load_silero_vad
from sounddevice import InputStream
from tokenizers import Tokenizer

# Local imports — src/ is added so voicecommand.* sub-modules resolve
CLANK_MOONSHINE_DEMO_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(CLANK_MOONSHINE_DEMO_DIR, ".."))
from onnx_model import MoonshineOnnxModel
from voicecommand.config import ClankConfig
from voicecommand.validation import (
    CommandValidator, ValidationError, COLOR_RGB, WLED_EFFECTS
)
from voicecommand.devices import DeviceRegistry, TYPE_SWITCH, TYPE_WLED
from voicecommand.secure_logging import setup_secure_logging

SAMPLING_RATE = 16000
CHUNK_SIZE = 512
LOOKBACK_CHUNKS = 5
MAX_SPEECH_SECS = 15

def build_system_prompt(registry):
    """Assemble the LLM system prompt for the currently-registered devices.

    The device list is injected at runtime from the registry so the model only
    ever knows about hardware that's actually configured. RGB-strip guidance is
    always included (the colour/effect vocabulary the validator enforces);
    on/off plug guidance and examples are always shown too so the format is
    learned even before a plug is added.
    """
    has_switch = registry.has_type(TYPE_SWITCH)
    switch_example = ""
    if has_switch:
        # Use a real registered plug name in the example when one exists.
        plug = next(d for d in registry.devices if d.type == TYPE_SWITCH)
        switch_example = (
            f'\n- "turn off the {plug.name}" -> '
            f'{{"action":"set_switch","target":"{plug.name}","parameters":{{"state":"off"}}}}'
        )

    return f"""/no_think You are a voice control system for smart-home devices. You must respond with EXACTLY ONE JSON object and nothing else - no markers, no multiple responses, no extra text.

The input comes from imperfect speech-to-text, so it is often garbled or
misheard. Be forgiving: match by sound and intent, not exact words. Only use
"unknown" when there is genuinely no reasonable interpretation.

Devices you control — set "target" to the one the user means, matching its name
or any of its "also called" aliases:
{registry.prompt_block()}

Every response has this shape:
{{
    "action": "<action>",
    "target": "<device name>",
    "parameters": {{ ... only the keys the user asked for ... }}
}}
If the user doesn't name a device and only one device can perform the action,
you may omit "target".

== RGB light strips — action "set_rgb" ==
Include only the parameters the user actually asked for:
- "state": "on" or "off"
- "color": one of red, green, blue, white, warm white, yellow, orange, amber,
  purple, violet, pink, magenta, cyan, teal, turquoise, lime, gold
- "brightness": integer 0-100 (a percentage)
- "effect": one of solid, blink, breathe, fade, heartbeat, random, colorloop,
  rainbow, strobe, strobe rainbow, strobe mega, blink rainbow, candle, fire, tv.
  Use "solid" for a plain steady colour or "stop the effect". Map intent:
  "pulse"/"breathing" -> breathe, "cycle colours" -> colorloop, "rainbow" ->
  rainbow, "flicker"/"candle light" -> candle, "flash" -> strobe, "flames" ->
  fire, "random colours" -> random, "tv"/"fake tv" -> tv.
- "speed": integer 0-100 — how FAST the current effect animates (0 = slowest,
  100 = fastest). Use for "faster/quicker/speed up" -> a high value like 85;
  "slower/calmer" -> a low value like 20.
- "intensity": integer 0-100 — the effect's strength/amount (effect-specific).
  Use for "more/less intense", "stronger/subtler".
Setting a colour, brightness, effect, speed, or intensity implies that strip
turns on, so you do not also need to add "state":"on" in that case. "dim" means
lower brightness; "bright" or "full" means brightness 100. speed and intensity
adjust whatever effect is already running, so "make the strobe quicker" needs
ONLY the speed (don't resend the effect unless the user is also changing it).

== On/off smart plugs — action "set_switch" ==
For devices listed above as a smart plug. The only parameter is "state" ("on"
or "off"); plugs have no colour, brightness, or effects.

State words: on/off, turn on/off, kill, cut, shut, enable/disable.

Examples:
- "turn the lights on" -> {{"action":"set_rgb","target":"strip","parameters":{{"state":"on"}}}}
- "turn off the leds" -> {{"action":"set_rgb","target":"strip","parameters":{{"state":"off"}}}}
- "make it red" -> {{"action":"set_rgb","target":"strip","parameters":{{"color":"red"}}}}
- "set the strip to blue" -> {{"action":"set_rgb","target":"strip","parameters":{{"color":"blue"}}}}
- "dim the lights to 20 percent" -> {{"action":"set_rgb","target":"strip","parameters":{{"brightness":20}}}}
- "warm white at half brightness" -> {{"action":"set_rgb","target":"strip","parameters":{{"color":"warm white","brightness":50}}}}
- "make the lights breathe" -> {{"action":"set_rgb","target":"strip","parameters":{{"effect":"breathe"}}}}
- "cycle through colours" -> {{"action":"set_rgb","target":"strip","parameters":{{"effect":"colorloop"}}}}
- "candle mode in orange" -> {{"action":"set_rgb","target":"strip","parameters":{{"color":"orange","effect":"candle"}}}}
- "strobe the lights" -> {{"action":"set_rgb","target":"strip","parameters":{{"effect":"strobe"}}}}
- "make the strobe quicker" -> {{"action":"set_rgb","target":"strip","parameters":{{"speed":85}}}}
- "fast rainbow" -> {{"action":"set_rgb","target":"strip","parameters":{{"effect":"rainbow","speed":85}}}}
- "stop the effect" -> {{"action":"set_rgb","target":"strip","parameters":{{"effect":"solid"}}}}{switch_example}

For commands that are not about any device, respond with:
{{
    "action": "unknown",
    "parameters": {{}}
}}

Remember: Return EXACTLY ONE JSON object with no additional text or markers."""


def _default_devices_path():
    """Path to the device registry: $CLANK_DEVICES, else config/devices.yaml at
    the repo root (resolved relative to this file so cwd doesn't matter)."""
    env = os.getenv("CLANK_DEVICES")
    if env:
        return env
    repo_root = os.path.normpath(os.path.join(CLANK_MOONSHINE_DEMO_DIR, "..", ".."))
    return os.path.join(repo_root, "config", "devices.yaml")


class MqttPublisher:
    """Publishes device commands to the MQTT broker, addressing any topic.

    Holds a single persistent connection (paho's background loop with automatic
    reconnect), so each voice command is just one tiny non-blocking publish — no
    per-command connect/handshake. One publisher serves every registered device
    (the WLED strip, plugs, ...); the per-device topic is passed at publish
    time. Credentials come from the environment (MQTT_USER / MQTT_PASS) and
    never touch the config file.
    """

    def __init__(self, config, logger):
        import paho.mqtt.client as mqtt  # lazy: only needed for MQTT control

        self.logger = logger

        # paho 2.x requires a callback API version; 1.x has no such argument.
        try:
            self.client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id="clank-controller"
            )
        except (AttributeError, TypeError):
            self.client = mqtt.Client(client_id="clank-controller")

        user = os.getenv("MQTT_USER", "clank")
        password = os.getenv("MQTT_PASS", "")
        if password:
            self.client.username_pw_set(user, password)
        else:
            logger.warning(
                "MQTT_PASS not set; connecting without credentials (the broker "
                "will reject this if it requires auth)."
            )

        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        # connect_async + loop_start never blocks startup: if the broker is down
        # the client keeps retrying in the background and publishes succeed once
        # it comes up.
        self.client.connect_async(
            config.mqtt.broker_host, config.mqtt.broker_port, keepalive=60
        )
        self.client.loop_start()
        logger.info(
            f"MQTT publisher -> {config.mqtt.broker_host}:{config.mqtt.broker_port}"
        )

    def publish(self, topic: str, payload):
        """Publish one command to a device's topic (qos 1, not retained —
        commands are momentary, but qos 1 gets a broker-level delivery ack so a
        single dropped packet doesn't silently lose the command). Dicts/lists
        are JSON-encoded (WLED state objects); strings are sent verbatim (plug
        ON/OFF payloads)."""
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        self.client.publish(topic, payload, qos=1, retain=False)


class VoiceProcessor:
    def __init__(self, model_name, config, logger):
        self.transcriber = Transcriber(model_name=model_name, rate=SAMPLING_RATE)
        self.config = config
        self.logger = logger

        # Device registry: drives which devices exist, validation of the LLM's
        # "target", and the device list injected into the system prompt. Adding
        # hardware is a config/devices.yaml edit — no code change here.
        self.registry = DeviceRegistry.from_file(_default_devices_path())
        self.validator = CommandValidator(self.registry)
        self.system_prompt = build_system_prompt(self.registry)

        # Wake word + privacy settings.
        self.wake_word = config.audio.wake_word.lower().strip()
        self.wake_engine = config.audio.wake_engine.lower().strip()
        self.require_wake_word = config.audio.require_wake_word
        # With the acoustic engine, the wake word is gated on audio before the
        # transcript exists, so the text-match gate must be off (the command
        # transcript won't contain the wake word).
        if self.wake_engine == "openwakeword":
            self.require_wake_word = False
        self.log_transcripts = config.security.log_transcripts
        # Common STT mishearings of the wake word, so a garbled "clank" still
        # triggers. Fuzzy matching below catches the rest.
        # Only genuine phonetic near-misses of "clank". Note the fuzzy match
        # below (ratio >= 0.72) already catches most of these; real words that
        # merely rhyme (e.g. "thank", "tank") are deliberately excluded so
        # everyday speech like "thank you" doesn't wake the system.
        self.wake_aliases = {
            self.wake_word, "clank", "clink", "clunk", "klank", "clang",
            "clack", "crank", "blank", "plank", "flank",
        }

        # One MQTT publisher shared by every device, constructed once so the
        # connection is reused for every command. If paho-mqtt isn't installed
        # the assistant still runs (device commands just warn) so non-MQTT
        # testing keeps working.
        try:
            self.mqtt = MqttPublisher(config, logger)
        except Exception as e:
            self.mqtt = None
            self.logger.warning(f"MQTT publisher unavailable: {e}")

    def _is_wake_token(self, tok):
        """True if a single token is the wake word or a close mishearing."""
        t = tok.lower().strip(".,!?;:'\"")
        return (
            t in self.wake_aliases
            or difflib.SequenceMatcher(None, t, self.wake_word).ratio() >= 0.72
        )

    def _strip_wake_word(self, text):
        """Detect the wake word and return (heard, command_text).

        Scans tokens for an exact alias or a close phonetic match (handles STT
        mishearings like 'clink'/'crank'/'blank'). On a hit, the wake word AND
        any wake-word echoes immediately following it are dropped; everything
        after that is the command.

        Stripping every leading wake token (not just the first) matters for the
        acoustic engine: the capture's pre-roll keeps the tail of "...clank",
        which transcribes as a leading "clank" — sometimes doubled — so a
        single-strip would leak "clank" to the LLM as a bogus command (it comes
        back as color="clank"). Here "clank clank" -> "" (discarded) and
        "clank clank red" -> "red".
        """
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake_token(tok):
                j = i + 1
                while j < len(tokens) and self._is_wake_token(tokens[j]):
                    j += 1
                return True, " ".join(tokens[j:]).strip()
        return False, ""

    def process_command(self, text):
        """Validate transcribed text, query LLM, validate response, forward to ESP32."""
        # Sanitize and validate the transcription before it touches the LLM prompt
        try:
            text = self.validator.validate_transcription(text)
        except ValidationError as e:
            self.logger.warning(f"Transcription validation failed: {e}")
            return

        # Wake-word gate. If the utterance isn't addressed to us, discard it
        # here — no LLM call, no logging of content, nothing retained. This is
        # what keeps everyday speech ephemeral.
        if self.require_wake_word:
            heard, command_text = self._strip_wake_word(text)
            if not heard:
                self.logger.debug("No wake word; utterance discarded")
                return
            if not command_text:
                self.logger.debug("Wake word only; no command")
                return
            text = command_text

        # Only now — once we know this is addressed to us — may we log the
        # transcript, and only if explicitly enabled for debugging.
        if self.log_transcripts:
            self.logger.info(f"Command transcript: {text}")

        try:
            payload = {
                "model": self.config.llm.model,
                "prompt": f"{self.system_prompt}\nUser command: {text}\nResponse:",
                "stream": False,
                "options": {
                    "temperature": self.config.llm.temperature,
                    "num_predict": self.config.llm.max_tokens,
                },
            }
            # Structured output: force a single valid JSON object so reasoning
            # models can't bury the answer in prose or hidden "thinking".
            if self.config.llm.response_format:
                payload["format"] = self.config.llm.response_format
            if self.config.llm.think is not None:
                payload["think"] = self.config.llm.think
            llm_response = requests.post(
                self.config.llm.endpoint,
                json=payload,
                timeout=self.config.llm.timeout,
            )
            llm_response.raise_for_status()

            response_text = llm_response.json()["response"].strip()

            # Validate and structurally check the LLM's JSON output
            try:
                parsed_json = self.validator.validate_llm_response(response_text)
            except ValidationError as e:
                self.logger.warning(f"LLM response validation failed: {e}")
                return

            if parsed_json["action"] == "set_rgb":
                params = parsed_json["parameters"]
                device = self.registry.get(parsed_json.get("target"))
                if device is None:
                    self.logger.warning(
                        f"set_rgb for unknown target {parsed_json.get('target')!r}"
                    )
                    return
                # Translate to WLED's JSON state API (published to the device's
                # topic, e.g. wled/clank/api).
                # Per-segment colour/effect go in "seg"; on/off and brightness are
                # top-level. Any colour/brightness/effect implies the strip is on
                # unless the user explicitly said "off".
                wled = {}
                seg = {}
                if "color" in params:
                    seg["col"] = [list(COLOR_RGB[params["color"]])]
                if "effect" in params:
                    seg["fx"] = WLED_EFFECTS[params["effect"]]
                # Effect speed (sx) and intensity (ix) are 0-255 in WLED; map
                # from our 0-100 percentages. These tune whatever effect is
                # active, so "make the strobe quicker" is just a high speed.
                if "speed" in params:
                    seg["sx"] = round(params["speed"] * 255 / 100)
                if "intensity" in params:
                    seg["ix"] = round(params["intensity"] * 255 / 100)
                if seg:
                    wled["seg"] = [seg]
                if "brightness" in params:
                    wled["bri"] = round(params["brightness"] * 255 / 100)
                state = params.get("state")
                if state == "off":
                    wled["on"] = False
                elif state == "on" or seg or "brightness" in params:
                    wled["on"] = True

                # Persist the resulting look so a mains power-cycle restores it.
                # WLED's "psave" snapshots the live state (after this call's
                # changes are applied) into a preset slot; the device is set to
                # boot into that slot (def.ps), so the strip comes back exactly
                # as it was instead of the factory amber default. Set
                # mqtt.persist_preset to 0 to disable (avoids a flash write per
                # command).
                # ib/sb make the preset include master brightness + on-state and
                # the segment, so the whole look is restored (a bare psave only
                # stores the segment colour). WLED applies this call's changes
                # first, then snapshots the resulting live state into the slot.
                # The slot is per-device (devices.yaml), falling back to the
                # global mqtt.persist_preset.
                slot = device.persist_preset
                if slot is None:
                    slot = self.config.mqtt.persist_preset
                if slot:
                    wled["psave"] = slot
                    wled["n"] = "clank-last"
                    wled["ib"] = True
                    wled["sb"] = True

                # Log the resolved command (never the raw speech).
                self.logger.info(f"Command(rgb): {device.name} <- {params}")
                if self.mqtt is None:
                    self.logger.error("RGB command but MQTT publisher is unavailable")
                else:
                    self.mqtt.publish(device.topic, wled)

            elif parsed_json["action"] == "set_switch":
                params = parsed_json["parameters"]
                device = self.registry.get(parsed_json.get("target"))
                if device is None:
                    self.logger.warning(
                        f"set_switch for unknown target {parsed_json.get('target')!r}"
                    )
                    return
                # On/off plug (OpenBeken/Tasmota): publish the raw on/off payload
                # to the device's command topic. No colour/brightness/effects.
                payload = (
                    device.on_payload if params["state"] == "on"
                    else device.off_payload
                )
                self.logger.info(f"Command(switch): {device.name} -> {params['state']}")
                if self.mqtt is None:
                    self.logger.error("Switch command but MQTT publisher is unavailable")
                else:
                    self.mqtt.publish(device.topic, payload)

        except Exception as e:
            self.logger.error(f"Error processing command: {e}")


class Transcriber:
    def __init__(self, model_name, rate=16000):
        models_dir = os.path.join(
            CLANK_MOONSHINE_DEMO_DIR, "..", "..", "models", "moonshine"
        )
        self.model = MoonshineOnnxModel(models_dir=models_dir)
        self.rate = rate
        tokenizer_path = os.path.join(
            CLANK_MOONSHINE_DEMO_DIR, "..", "assets", "tokenizer.json"
        )
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.inference_secs = 0
        self.number_inferences = 0
        self.speech_secs = 0
        self.__call__(np.zeros(int(rate), dtype=np.float32))  # Warmup

    def __call__(self, speech):
        self.number_inferences += 1
        self.speech_secs += len(speech) / self.rate
        start_time = time.time()
        tokens = self.model.generate(speech[np.newaxis, :].astype(np.float32))
        text = self.tokenizer.decode_batch(tokens)[0]
        self.inference_secs += time.time() - start_time
        return text


# SHA256 of the openWakeWord 0.4.0 bundled ONNX models we rely on. Audited on
# 2026-06-08: each loads with stock onnxruntime CPU kernels only (no custom
# ops), is self-contained (no external data), and embeds no URLs/paths/libs.
# These are integrity-checked before any file is handed to onnxruntime, so a
# tampered or swapped model is rejected rather than executed.
_KNOWN_OWW_SHA256 = {
    "melspectrogram.onnx":   "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
    "embedding_model.onnx":  "ba754db3cd768a524c655ea90655ee5e6055a43b8dfd29366a11e93716ae9e51",
    "hey_jarvis_v0.1.onnx":  "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
    "alexa_v0.1.onnx":       "6ff566a01d12670e8d9e3c59da32651db1575d17272a601b7f8a39283dfbae3e",
    "hey_mycroft_v0.1.onnx": "785bdf5655863ae47553b23793aa108c7b0152d4823f7869b41f2d2d765912fc",
    "hey_marvin_v0.1.onnx":  "b6d4b794ddf2e1d6f29e9f45848e24858e2edd0d810b14e0c1c70dda9a1fcbf0",
    # Our own "hey clank" model, trained locally (openWakeWord 0.4.0 pipeline)
    # and committed at models/wakeword/hey_clank.onnx. Audited 2026-06-11:
    # ai.onnx opset 13, standard DNN ops only (Gemm/Relu/Sigmoid/...), no custom
    # domains, no external data, no metadata, no embedded URLs/paths; loads and
    # runs under the stock onnxruntime CPU provider.
    "hey_clank.onnx":        "1d0dfa7ba9ead226b62c222c38b99bb5ea8262eb116996251e9d6289162d72c1",
}


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


class WakeWordDetector:
    """Acoustic wake-word gate using openWakeWord.

    Runs a small ONNX model on the raw audio stream so the (much heavier) STT
    model only runs once the wake word has fired. Models ship bundled with the
    openwakeword package, so this works fully offline.

    All ONNX files are SHA256-checked against a known-good list before being
    loaded — known models that don't match are rejected; custom models log
    their hash so you can verify provenance and pin them.
    """

    def __init__(self, model_spec, threshold, logger):
        # Imported lazily so the default "text" engine needs no extra deps.
        from openwakeword.model import Model

        self.threshold = threshold
        self.logger = logger
        path = self._resolve(model_spec)
        # Integrity-check the wake model and the always-used feature models
        # BEFORE onnxruntime touches any of them.
        self._verify(path)
        self._verify_feature_models()
        self.model = Model(wakeword_model_paths=[path])
        self.name = list(self.model.models.keys())[0]
        logger.info(
            f"openWakeWord loaded: {self.name} (threshold {threshold})"
        )

    def _verify(self, path):
        """Reject a known model that fails its hash; log unknown (custom) ones."""
        name = os.path.basename(path)
        digest = _sha256_file(path)
        known = _KNOWN_OWW_SHA256.get(name)
        if known is None:
            self.logger.warning(
                f"openWakeWord model {name!r} is not in the known-good list "
                f"(sha256={digest}). Verify its provenance, then pin it."
            )
        elif digest != known:
            raise ValueError(
                f"openWakeWord model {name!r} failed its integrity check: "
                f"expected {known}, got {digest}. Refusing to load."
            )

    def _verify_feature_models(self):
        """Hash-check the shared melspectrogram + embedding models openWakeWord
        loads internally for every wake model."""
        import openwakeword

        mdir = os.path.join(
            os.path.dirname(openwakeword.__file__), "resources", "models"
        )
        for fn in ("melspectrogram.onnx", "embedding_model.onnx"):
            p = os.path.join(mdir, fn)
            if os.path.exists(p):
                self._verify(p)

    @staticmethod
    def _resolve(spec):
        """Resolve a builtin model name or a path to a .onnx file."""
        if os.path.exists(spec):
            return spec
        # A relative path (e.g. the default models/wakeword/hey_clank.onnx) may
        # be given against the repo root rather than the current directory, so
        # try resolving it there before falling back to the builtin lookup.
        repo_root = os.path.normpath(
            os.path.join(CLANK_MOONSHINE_DEMO_DIR, "..", "..")
        )
        repo_rel = os.path.join(repo_root, spec)
        if os.path.exists(repo_rel):
            return repo_rel
        import openwakeword

        mdir = os.path.join(
            os.path.dirname(openwakeword.__file__), "resources", "models"
        )
        candidate = spec if spec.endswith(".onnx") else f"{spec}_v0.1.onnx"
        path = os.path.join(mdir, candidate)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"openWakeWord model not found: {spec!r} (looked for {path}). "
                f"Use a builtin name (hey_jarvis/alexa/hey_mycroft/hey_marvin) "
                f"or a path to a custom .onnx."
            )
        return path

    def score(self, chunk_f32):
        """Return the wake-word probability for a float32 [-1, 1] audio chunk."""
        pcm = (np.clip(chunk_f32, -1.0, 1.0) * 32767).astype(np.int16)
        preds = self.model.predict(pcm)
        return float(preds[self.name])

    def reset(self):
        """Clear internal buffers so a fresh detection starts cleanly."""
        if hasattr(self.model, "reset"):
            self.model.reset()


def create_input_callback(q):
    def input_callback(data, frames, time, status):
        if status:
            q.put((data.copy().flatten(), status))
        else:
            q.put((data.copy().flatten(), status))
    return input_callback


def main():
    parser = argparse.ArgumentParser(description="Clank voice command system")
    parser.add_argument(
        "--model_name",
        default="moonshine/base",
        choices=["moonshine/base", "moonshine/tiny"],
    )
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument(
        "--wake-engine",
        choices=["text", "openwakeword"],
        help="Override audio.wake_engine for this run",
    )
    parser.add_argument(
        "--oww-model",
        help="Override audio.oww_model (builtin name or path to a .onnx)",
    )
    parser.add_argument(
        "--oww-threshold",
        type=float,
        help="Override audio.oww_threshold (0-1; lower = more sensitive)",
    )
    parser.add_argument(
        "--oww-debug",
        action="store_true",
        help="Log the peak wake-word score each second (diagnostics)",
    )
    args = parser.parse_args()

    # Load config (falls back to defaults if file not found)
    config = ClankConfig(args.config)
    config.ensure_directories()

    # CLI overrides (applied before VoiceProcessor reads the config)
    if args.wake_engine:
        config.audio.wake_engine = args.wake_engine
    if args.oww_model:
        config.audio.oww_model = args.oww_model
    if args.oww_threshold is not None:
        config.audio.oww_threshold = args.oww_threshold
    if args.oww_debug:
        config.audio.oww_debug = True

    # Structured rotating-file + audit logging
    logger, audit_logger, _ = setup_secure_logging(config)

    logger.info("Starting Clank voice command system")

    voice_processor = VoiceProcessor(args.model_name, config, logger)

    vad_model = load_silero_vad(onnx=True)
    vad_iterator = VADIterator(
        model=vad_model,
        sampling_rate=SAMPLING_RATE,
        threshold=config.audio.vad_threshold,
        min_silence_duration_ms=config.audio.min_silence_duration_ms,
    )

    q = Queue()
    stream = InputStream(
        samplerate=SAMPLING_RATE,
        channels=1,
        blocksize=CHUNK_SIZE,
        dtype=np.float32,
        callback=create_input_callback(q),
    )

    stream.start()
    with stream:
        try:
            if voice_processor.wake_engine == "openwakeword":
                run_wake_engine_loop(q, voice_processor, vad_iterator, config, logger)
            else:
                run_text_loop(q, voice_processor, vad_iterator, config, logger)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            audit_logger.stop()
            stream.close()


def run_text_loop(q, voice_processor, vad_iterator, config, logger):
    """Default engine: transcribe every utterance, then text-match the wake word
    inside process_command. STT runs on all speech."""
    speech = np.empty(0, dtype=np.float32)
    recording = False
    lookback_size = LOOKBACK_CHUNKS * CHUNK_SIZE

    logger.info("Listening. Press Ctrl+C to quit.")

    while True:
        chunk, status = q.get()
        if status:
            logger.warning(f"Stream status: {status}")

        speech = np.concatenate((speech, chunk))
        if not recording:
            speech = speech[-lookback_size:]

        speech_dict = vad_iterator(chunk)
        if speech_dict:
            if "start" in speech_dict and not recording:
                recording = True

            if "end" in speech_dict and recording:
                recording = False
                # Raw transcript stays local and is discarded after
                # process_command returns — it is never logged here.
                # Wake-word gating + transcript logging live inside
                # process_command so non-command speech leaves no trace.
                text = voice_processor.transcriber(speech)
                voice_processor.process_command(text)
                speech = np.empty(0, dtype=np.float32)

        elif recording:
            if (len(speech) / SAMPLING_RATE) > MAX_SPEECH_SECS:
                recording = False
                text = voice_processor.transcriber(speech)
                voice_processor.process_command(text)
                speech = np.empty(0, dtype=np.float32)
                vad_iterator.reset_states()


def run_wake_engine_loop(q, voice_processor, vad_iterator, config, logger):
    """openWakeWord engine: a small acoustic model gates the stream. Moonshine
    only runs after the wake word fires, capturing the command that follows
    until VAD detects end-of-speech (or a timeout)."""
    detector = WakeWordDetector(
        config.audio.oww_model, config.audio.oww_threshold, logger
    )

    LISTENING, CAPTURING = 0, 1
    state = LISTENING
    speech = np.empty(0, dtype=np.float32)
    got_speech = False
    capture_start = 0.0

    threshold = config.audio.oww_threshold
    # Edge-trigger: fire once when the score crosses the threshold, then disarm
    # until it decays back below rearm_threshold. The detector is fed EVERY
    # frame (even while capturing a command) so its internal feature buffer
    # never freezes on the wake word — that, plus disarming, is what stops the
    # wake word's own lingering score from re-firing once we return to listening.
    rearm_threshold = threshold * 0.5
    armed = True

    # Pre-roll buffer: the last command_preroll_s of audio before the wake
    # fires, prepended to the capture so a fast command onset isn't clipped.
    preroll_samples = int(config.audio.command_preroll_s * SAMPLING_RATE)
    lookback = np.empty(0, dtype=np.float32)

    debug = config.audio.oww_debug
    peak_score = 0.0
    peak_amp = 0.0
    last_debug = time.time()

    logger.info("Listening for wake word. Press Ctrl+C to quit.")

    while True:
        chunk, status = q.get()
        if status:
            logger.warning(f"Stream status: {status}")

        # Always score, in both states, to keep the rolling buffer current.
        score = detector.score(chunk)
        if not armed and score < rearm_threshold:
            armed = True

        if debug:
            peak_score = max(peak_score, score)
            peak_amp = max(peak_amp, float(np.abs(chunk).max()))
            now = time.time()
            if now - last_debug >= 1.0:
                logger.info(
                    f"[oww] state={'LISTEN' if state == LISTENING else 'CAPTURE'} "
                    f"armed={int(armed)} peak score={peak_score:.3f} "
                    f"mic peak amp={peak_amp:.3f}"
                )
                peak_score = peak_amp = 0.0
                last_debug = now

        if state == LISTENING:
            # Keep a rolling pre-roll of recent audio.
            lookback = np.concatenate((lookback, chunk))[-preroll_samples:]
            if armed and score >= threshold:
                logger.info("Wake word detected")
                armed = False
                vad_iterator.reset_states()
                # Seed the capture with the pre-roll so the command onset that
                # was spoken during wake-detection latency isn't lost.
                speech = lookback.copy()
                lookback = np.empty(0, dtype=np.float32)
                got_speech = False
                capture_start = time.time()
                state = CAPTURING
            continue

        # CAPTURING: accumulate the command and watch for end-of-speech.
        speech = np.concatenate((speech, chunk))
        speech_dict = vad_iterator(chunk)
        if speech_dict and "start" in speech_dict:
            got_speech = True

        end_of_speech = bool(speech_dict and "end" in speech_dict and got_speech)
        too_long = (len(speech) / SAMPLING_RATE) > MAX_SPEECH_SECS
        timed_out = (time.time() - capture_start) > config.audio.command_timeout_s

        if end_of_speech or too_long or (timed_out and got_speech):
            text = voice_processor.transcriber(speech)
            voice_processor.process_command(text)
            state = LISTENING
            vad_iterator.reset_states()
        elif timed_out and not got_speech:
            logger.debug("Wake word fired but no command followed; resetting")
            state = LISTENING
            vad_iterator.reset_states()


if __name__ == "__main__":
    main()
