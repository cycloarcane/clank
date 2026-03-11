#!/bin/bash
# Clank Startup Script

cd "/home/r/Documents/clank"
source .venv/bin/activate

# Load environment variables (set -a exports every variable defined by source)
if [[ -f .env ]]; then
    set -a
    # shellcheck source=/dev/null
    source .env
    set +a
fi

echo "Starting Clank Voice Assistant..."
echo "Press Ctrl+C to stop"

python3 src/voicecommand/voice_LED_control.py "$@"
