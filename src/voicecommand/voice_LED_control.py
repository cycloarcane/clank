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

# Local import of Moonshine ONNX model
CLANK_MOONSHINE_DEMO_DIR = os.path.dirname(__file__)
sys.path.append(os.path.join(CLANK_MOONSHINE_DEMO_DIR, ".."))
from onnx_model import MoonshineOnnxModel

SAMPLING_RATE = 16000
CHUNK_SIZE = 512
LOOKBACK_CHUNKS = 5
MAX_SPEECH_SECS = 15
MIN_REFRESH_SECS = 0.2

# LLM API Configuration
LLM_ENDPOINT = "http://127.0.0.1:5000/v1/completions"

SYSTEM_PROMPT = """You are a voice control system for LED lights. You must respond with EXACTLY ONE JSON object and nothing else - no markers, no multiple responses, no extra text.

Commands can include:
- Turning LEDs on/off: "Computer turn on red LED"
- Setting brightness: "Computer set blue LED to 50%"

Response format:
{
    "action": "led_control",
    "parameters": {
        "color": string,  // The LED color (red, blue, green)
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
    def __init__(self, model_name):
        self.transcriber = Transcriber(model_name=model_name, rate=SAMPLING_RATE)
        self.logger = logging.getLogger("VoiceProcessor")

    def extract_json_from_text(self, text):
        """Extract the first valid JSON object from text"""
        try:
            # Find the first { and last } in the text
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                json_str = text[start:end + 1]
                return json.loads(json_str)
        except json.JSONDecodeError:
            return None
        return None

    def process_command(self, text):
        """Send transcribed text to LLM with system prompt"""
        try:
            payload = {
                "prompt": f"{SYSTEM_PROMPT}\nUser command: {text}\nResponse:",
                "max_tokens": 150,  # Increased for brightness commands
                "temperature": 0.0,  # Set to 0 for most consistent responses
                "stop": ["\n", "://"]  # Stop on newlines or protocol markers
            }
            response = requests.post(LLM_ENDPOINT, json=payload)
            response.raise_for_status()
            
            print("\nLLM Response:")
            print("-------------")
            try:
                llm_response = response.json()
                response_text = llm_response['choices'][0]['text'].strip()
                parsed_json = self.extract_json_from_text(response_text)
                if parsed_json:
                    print(json.dumps(parsed_json, indent=2))
                else:
                    print("Failed to parse JSON from response:")
                    print(response_text)
            except Exception as e:
                print(f"Error processing response: {e}")
                print("Raw response:", response.text)
            print("-------------\n")
            
        except Exception as e:
            self.logger.error(f"Error processing command: {e}")

class Transcriber:
    def __init__(self, model_name, rate=16000):
        self.model = MoonshineOnnxModel(model_name=model_name)
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
            print(status)
        q.put((data.copy().flatten(), status))
    return input_callback

def main():
    parser = argparse.ArgumentParser(description="Voice command system with LLM response debugging")
    parser.add_argument(
        "--model_name",
        default="moonshine/base",
        choices=["moonshine/base", "moonshine/tiny"],
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Initialize components
    voice_processor = VoiceProcessor(args.model_name)
    
    vad_model = load_silero_vad(onnx=True)
    vad_iterator = VADIterator(
        model=vad_model,
        sampling_rate=SAMPLING_RATE,
        threshold=0.5,
        min_silence_duration_ms=300,
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

    print("Voice command system started. Press Ctrl+C to quit.")
    print("Speak commands and see raw LLM responses.")
    
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
                        start_time = time.time()

                    if "end" in speech_dict and recording:
                        recording = False
                        # Process the complete utterance
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
            stream.close()

if __name__ == "__main__":
    main()