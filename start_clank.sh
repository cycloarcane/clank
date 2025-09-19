#!/bin/bash
# Clank Startup Script

cd "/home/r/Documents/clank"
source .venv/bin/activate

# Load environment variables
if [[ -f .env ]]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "Starting Clank Voice Assistant..."
echo "Press Ctrl+C to stop"

python3 src/voicecommand/voice_LED_control.py "$@"
