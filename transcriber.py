import warnings
import moonshine
from pathlib import Path

def transcribe_audio(audio_file: Path, model_path: str) -> str:
    """Transcribe audio file using moonshine."""
    warnings.filterwarnings("ignore", message="You are using a softmax over axis 3")
    
    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file {audio_file} does not exist.")
    
    try:
        print("Transcribing audio...")
        transcription = moonshine.transcribe(audio_file, model_path)
        return transcription
    except Exception as e:
        raise Exception(f"Transcription error: {e}")