import warnings
import moonshine
from pathlib import Path

def main():
    # Suppress specific warnings
    warnings.filterwarnings("ignore", message="You are using a softmax over axis 3")

    # Define file paths
    assets_dir = Path('./')
    audio_file = assets_dir / 'test.wav'
    model_path = 'moonshine/base'

    # Check if the audio file exists
    if not audio_file.exists():
        print(f"Error: Audio file {audio_file} does not exist.")
        return

    try:
        # Transcribe audio file
        transcription = moonshine.transcribe(audio_file, model_path)
        print("Transcription Result:")
        print(transcription)
    except Exception as e:
        print(f"An error occurred during transcription: {e}")

if __name__ == "__main__":
    main()
