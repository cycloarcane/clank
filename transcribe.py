import warnings
import subprocess
import signal
import os
from pathlib import Path
import moonshine

def record_audio(audio_file):
    """Start recording audio with sox."""
    try:
        print("Recording audio... Press ENTER to stop recording.")
        
        # Start sox process in the background
        sox_process = subprocess.Popen(['sox', '-d', str(audio_file)])
        
        # Wait for the user to press ENTER to stop recording
        input()
        
        # Stop the sox process
        sox_process.send_signal(signal.SIGINT)
        sox_process.wait()
        print(f"Recording stopped. Audio saved to {audio_file}")
    except Exception as e:
        print(f"Error during audio recording: {e}")
        if sox_process and sox_process.poll() is None:  # Ensure process is stopped
            sox_process.terminate()

def main():
    # Suppress specific warnings
    warnings.filterwarnings("ignore", message="You are using a softmax over axis 3")

    # Define file paths
    assets_dir = Path('./')
    audio_file = assets_dir / 'example.wav'
    model_path = 'moonshine/base'

    # Record audio
    record_audio(audio_file)

    # Check if the audio file exists
    if not audio_file.exists():
        print(f"Error: Audio file {audio_file} does not exist.")
        return

    # Transcribe the audio file
    try:
        print("Transcribing audio...")
        transcription = moonshine.transcribe(audio_file, model_path)
        print("Transcription Result:")
        print(transcription)
    except Exception as e:
        print(f"An error occurred during transcription: {e}")

if __name__ == "__main__":
    main()
