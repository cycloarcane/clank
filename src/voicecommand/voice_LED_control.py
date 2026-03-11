import argparse
import os
import sys
import time
import json
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

SYSTEM_PROMPT = """/nothink You are a voice control system for LED lights. You must respond with EXACTLY ONE JSON object and nothing else - no markers, no multiple responses, no extra text.

Commands can include:
- Turning individual LEDs on/off: "Computer turn on red LED"
- Turning all LEDs on/off: "Computer turn on all LEDs" or "Computer turn off all LEDs"
- Setting brightness: "Computer set blue LED to 50%"

Response format:
{
    "action": "led_control",
    "parameters": {
        "color": string,  // The LED color (red, blue, green) OR "all" for all LEDs
        "state": string,  // "on" or "off"
        "brightness": number | null  // 0-100 if specified, null if not
    }
}

For non-LED commands, respond with:
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
        self.esp32_endpoint = (
            f"http://{os.getenv('ESP32_IP', '192.168.0.18')}/led-control"
        )
        # Optional shared key for ESP32 authentication (set ESP32_API_KEY env var)
        esp32_api_key = os.getenv("ESP32_API_KEY", "")
        self.esp32_headers = {"X-API-Key": esp32_api_key} if esp32_api_key else {}

    def process_command(self, text):
        """Validate transcribed text, query LLM, validate response, forward to ESP32."""
        # Sanitize and validate the transcription before it touches the LLM prompt
        try:
            text = self.validator.validate_transcription(text)
        except ValidationError as e:
            self.logger.warning(f"Transcription validation failed: {e}")
            return

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

            self.logger.info(f"Command parsed: {json.dumps(parsed_json)}")

            if parsed_json["action"] == "led_control":
                try:
                    esp32_response = requests.post(
                        self.esp32_endpoint,
                        json=parsed_json,
                        headers=self.esp32_headers,
                        timeout=self.config.network.connection_timeout,
                    )
                    esp32_response.raise_for_status()
                    self.logger.info(f"ESP32 response: {esp32_response.text}")
                except requests.exceptions.RequestException as e:
                    self.logger.error(f"Error sending command to ESP32: {e}")

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
    args = parser.parse_args()

    # Load config (falls back to defaults if file not found)
    config = ClankConfig(args.config)
    config.ensure_directories()

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

    speech = np.empty(0, dtype=np.float32)
    recording = False
    lookback_size = LOOKBACK_CHUNKS * CHUNK_SIZE

    logger.info("Listening. Press Ctrl+C to quit.")

    stream.start()
    with stream:
        try:
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
                        text = voice_processor.transcriber(speech)
                        logger.info(f"Transcribed: {text}")
                        voice_processor.process_command(text)
                        speech = np.empty(0, dtype=np.float32)

                elif recording:
                    if (len(speech) / SAMPLING_RATE) > MAX_SPEECH_SECS:
                        recording = False
                        text = voice_processor.transcriber(speech)
                        logger.info(f"Transcribed (max length): {text}")
                        voice_processor.process_command(text)
                        speech = np.empty(0, dtype=np.float32)
                        vad_iterator.reset_states()

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            audit_logger.stop()
            stream.close()


if __name__ == "__main__":
    main()
