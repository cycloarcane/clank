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
from voicecommand.validation import CommandValidator, ValidationError
from voicecommand.secure_logging import setup_secure_logging

SAMPLING_RATE = 16000
CHUNK_SIZE = 512
LOOKBACK_CHUNKS = 5
MAX_SPEECH_SECS = 15

SYSTEM_PROMPT = """/no_think You are a voice control system for room lighting. You must respond with EXACTLY ONE JSON object and nothing else - no markers, no multiple responses, no extra text.

The input comes from imperfect speech-to-text, so it is often garbled or
misheard. Be forgiving: match by sound and intent, not exact words. If a phrase
plausibly refers to a known load, map it to that load. Only use "unknown" when
there is genuinely no reasonable lighting interpretation.

Controllable loads:
- "big_lights" — the main room/ceiling lights. Match phrases like: "big lights",
  "main lights", "overhead lights", "the lights", and common mishearings such as
  "big lie", "big light", "ig light", "the big lies", "pig lights", "big nights".
- "leds" — the LED strip. Match: "leds", "led", "led strip", "strip lights",
  "mood lights", and mishearings such as "let", "leads", "ledd", "led's", "ledge".
- "all" — every load at once ("everything", "all the lights", "all lights").

State ("on" / "off"): infer from words like on/off, turn on/off, kill, cut,
shut, enable/disable. Trailing "on"/"off" usually sets the state even if the
load name is garbled (e.g. "ig light off" -> big_lights off).

Examples:
- "big lie on" -> {"action":"set_load","parameters":{"load":"big_lights","state":"on"}}
- "ig light off" -> {"action":"set_load","parameters":{"load":"big_lights","state":"off"}}
- "turn the leds on" -> {"action":"set_load","parameters":{"load":"leds","state":"on"}}
- "kill all the lights" -> {"action":"set_load","parameters":{"load":"all","state":"off"}}

Response format:
{
    "action": "set_load",
    "parameters": {
        "load": string,  // "big_lights", "leds", or "all"
        "state": string  // "on" or "off"
    }
}

For commands that do not match a known load, respond with:
{
    "action": "unknown",
    "parameters": {}
}

Remember: Return EXACTLY ONE JSON object with no additional text or markers."""


class VoiceProcessor:
    def __init__(self, model_name, config, logger):
        self.transcriber = Transcriber(model_name=model_name, rate=SAMPLING_RATE)
        self.validator = CommandValidator()
        self.config = config
        self.logger = logger

        esp32_ip = os.getenv("ESP32_IP", "192.168.0.18")
        # HTTPS is used when a pinned CA cert is provided (ESP32_CA_CERT), or
        # forced with ESP32_USE_HTTPS=true. The cert is generated alongside the
        # firmware by scripts/generate_esp32_cert.py.
        ca_cert = os.getenv("ESP32_CA_CERT", "")
        use_https = bool(ca_cert) or os.getenv("ESP32_USE_HTTPS", "").lower() in (
            "1", "true", "yes", "on"
        )

        if use_https:
            self.esp32_endpoint = f"https://{esp32_ip}/led-control"
            # Pin to the device's self-signed cert when supplied; otherwise fall
            # back to default verification (and warn — this will likely fail for
            # a self-signed device, which is the point: don't silently skip TLS).
            self.esp32_verify = ca_cert if ca_cert else True
            if not ca_cert:
                self.logger.warning(
                    "ESP32_USE_HTTPS set without ESP32_CA_CERT; TLS verification "
                    "will use system trust and likely reject the device cert. "
                    "Set ESP32_CA_CERT to the pinned certificate."
                )
        else:
            self.esp32_endpoint = f"http://{esp32_ip}/led-control"
            self.esp32_verify = True

        # Optional shared key for ESP32 authentication (set ESP32_API_KEY env var)
        esp32_api_key = os.getenv("ESP32_API_KEY", "")
        self.esp32_headers = {"X-API-Key": esp32_api_key} if esp32_api_key else {}
        # The esp_https_server has very few concurrent TLS socket slots; ask it
        # to close each connection so the slot is freed immediately instead of
        # lingering in keep-alive and blocking the next command.
        self.esp32_headers["Connection"] = "close"

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

    def _strip_wake_word(self, text):
        """Detect the wake word and return (heard, command_text).

        Scans tokens for an exact alias or a close phonetic match (handles STT
        mishearings like 'clink'/'crank'/'blank'). On a hit, everything after
        the wake word is the command; text before/including it is dropped.
        """
        tokens = text.split()
        for i, tok in enumerate(tokens):
            t = tok.lower().strip(".,!?;:'\"")
            if (
                t in self.wake_aliases
                or difflib.SequenceMatcher(None, t, self.wake_word).ratio() >= 0.72
            ):
                return True, " ".join(tokens[i + 1:]).strip()
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
                "prompt": f"{SYSTEM_PROMPT}\nUser command: {text}\nResponse:",
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

            if parsed_json["action"] == "set_load":
                params = parsed_json["parameters"]
                # Log the resolved command (load -> state), never the raw
                # speech. This is the only command record kept by default.
                self.logger.info(
                    f"Command: {params['load']} -> {params['state']}"
                )
                # One retry: a single TLS/WiFi latency spike shouldn't drop a
                # command. The ESP32 action is idempotent (set on/off), so
                # re-sending is safe.
                last_err = None
                for attempt in range(2):
                    try:
                        esp32_response = requests.post(
                            self.esp32_endpoint,
                            json=parsed_json,
                            headers=self.esp32_headers,
                            timeout=self.config.network.connection_timeout,
                            verify=self.esp32_verify,
                        )
                        esp32_response.raise_for_status()
                        self.logger.info(f"ESP32 response: {esp32_response.text}")
                        last_err = None
                        break
                    except requests.exceptions.RequestException as e:
                        last_err = e
                        if attempt == 0:
                            self.logger.warning(
                                f"ESP32 request failed ({e}); retrying once"
                            )
                if last_err is not None:
                    self.logger.error(f"Error sending command to ESP32: {last_err}")

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
