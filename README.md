# Clank

Clank is a voice-controlled LED automation project that combines speech recognition, local AI models, and ESP32-controlled hardware. Built on top of the [Moonshine](https://github.com/usefulsensors/moonshine) speech recognition system, it enables voice-activated control of LED lights through natural language commands.

## Vision

Clank allows users to control LED lights through simple spoken commands. The system flow is:

1. **User Speech**: Audio is captured via the default microphone using sounddevice
2. **Voice Activity Detection**: Using Silero VAD to detect speech segments
3. **Transcription**: Speech is transcribed into text using Moonshine's speech recognition model
4. **AI Processing**: The text is sent to a locally hosted LLM (running at `127.0.0.1:5000`) for interpretation
5. **LED Control**: The LLM returns structured JSON output which will be used to control LEDs via ESP32 GPIOs

## Current Status

The project has achieved several key milestones:

- **Speech Recognition**: Successfully implemented using Moonshine's ONNX models
- **Voice Activity Detection**: Integrated Silero VAD for accurate speech detection
- **Command Processing**: LLM successfully generates structured JSON responses for LED control
- **Example Response**:
  ```json
  {
    "action": "led_control",
    "parameters": {
      "color": "blue",
      "state": "on",
      "brightness": 50
    }
  }
  ```

## Features

### Implemented
- **Audio Capture**: Uses sounddevice for real-time audio input
- **Speech Detection**: Silero VAD for precise voice activity detection
- **Speech Recognition**: Moonshine-powered transcription
- **Command Processing**: Local LLM interpretation with structured JSON output

### In Progress
- **ESP32 Integration**: Development of firmware to receive and process LLM commands
- **LED Control**: GPIO management for LED state and brightness control

### Planned
- **Extended Hardware Control**: Support for multiple LED arrays
- **Advanced Voice Commands**: More complex lighting patterns and scenes
- **Web Interface**: Configuration and monitoring dashboard

## Installation

1. **Set Required Environment Variable**:
   ```bash
   export KERAS_BACKEND=torch
   ```

2. **Clone the Repository**:
   ```bash
   git clone https://github.com/cycloarcane/clank.git
   cd clank
   ```

3. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Local LLM**:
   Ensure your local LLM server is running at `127.0.0.1:5000`

## Usage

Run the voice control script:

```bash
python voice_LED_control.py
```

Available voice commands:
- "Computer turn on red LED"
- "Computer set blue LED to 50%"
- "Computer turn off green LED"

## Project Structure

- `voice_LED_control.py`: Main script for voice capture and processing
- `onnx_model.py`: Moonshine model wrapper for speech recognition
- `requirements.txt`: Python dependencies
- `README.md`: Project documentation

## Acknowledgments

This project heavily builds upon the [Moonshine](https://github.com/usefulsensors/moonshine) speech recognition system and their live_captions demo. Special thanks to the Moonshine team:

```bibtex
@misc{jeffries2024moonshinespeechrecognitionlive,
      title={Moonshine: Speech Recognition for Live Transcription and Voice Commands}, 
      author={Nat Jeffries and Evan King and Manjunath Kudlur and Guy Nicholson and James Wang and Pete Warden},
      year={2024},
      eprint={2410.15608},
      archivePrefix={arXiv},
      primaryClass={cs.SD},
      url={https://arxiv.org/abs/2410.15608}, 
}
```

## Contributing

Contributions are welcome! If you'd like to help build Clank, please submit a pull request or open an issue for any feature requests or bug fixes.

## Contact

For questions or support:
- **Email**: cycloarkane@gmail.com
- **GitHub**: [cycloarcane](https://github.com/cycloarcane)

## License

This project is licensed under a modified non-commercial GNU 3.0 license.

---

Join us in building the future of voice-controlled lighting! 🎤💡