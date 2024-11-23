import subprocess
import signal
from pathlib import Path

def record_audio(audio_file):
    """Start recording audio with sox."""
    sox_process = None
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
        if sox_process and sox_process.poll() is None:
            sox_process.terminate()