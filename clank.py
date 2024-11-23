import warnings
import logging
from pathlib import Path
from audio_handler import record_audio
from transcriber import transcribe_audio
from model_client import ModelClient

def setup_logging():
    """Set up logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def main():
    setup_logging()
    try:
        # Define file paths
        assets_dir = Path('./')
        audio_file = assets_dir / 'example.wav'
        model_path = 'moonshine/base'
        
        # Record audio
        record_audio(audio_file)
        
        # Transcribe audio
        transcription = transcribe_audio(audio_file, model_path)
        logging.info("\nTranscription Result:")
        print(transcription)
        
        # Get model response
        logging.info("\nGetting model response...")
        model_client = ModelClient()
        model_output = model_client.get_completion(transcription)
        
        print("\nModel Response:")
        print(f"Text: {model_output.text}")
        print(f"Model: {model_output.model}")
        print(f"Total tokens: {model_output.total_tokens}")
        if model_output.finish_reason:
            print(f"Finish reason: {model_output.finish_reason}")
        
    except Exception as e:
        logging.error(f"Error: {e}")

if __name__ == "__main__":
    main()