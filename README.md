
# Clank

Clank is an ambitious project that bridges voice commands, artificial intelligence, and physical automation. It uses speech-to-text transcription, local AI models, and ESP32-controlled hardware to enable voice-activated home or industrial automation.

## Vision

Clank will allow users to control physical devices such as LEDs, motors, and other hardware through simple spoken commands. The system flow is:

1. **User Speech**: Audio is captured via a microphone.
2. **Transcription**: Speech is transcribed into text using [Moonshine](https://github.com) and Sox.
3. **AI Integration**: The text is sent to a locally hosted LLM (running at `127.0.0.1:5000`) for interpretation and processing.
4. **Hardware Control**: The LLM returns structured output to a listener, which activates specific GPIOs on an ESP32 to perform actions (e.g., light LEDs or turn on motors).

## Current Status

The project is in its early stages, focusing on the **speech-to-text transcription** pipeline:

- Audio recording is implemented using Sox.
- Transcription is performed using the Moonshine model.

## Features (Implemented and Planned)

### Implemented
- **Record Audio**: Uses Sox to capture audio from the default microphone.
- **Transcribe Speech**: Automatically converts recorded audio into text.

### Planned
- **Integrate LLM**: Transcribed text will be sent to a locally hosted LLM for interpretation.
- **Device Control**: Use structured output from the LLM to control hardware via ESP32 GPIOs.
- **Home/Industrial Automation**: Build automation systems for homes and industrial settings.

## Installation

1. **Install Sox** (on Arch Linux):
   ```bash
   sudo pacman -S sox
   ```

2. **Clone the Repository**:
   ```bash
   git clone https://github.com/cycloarcane/clank.git
   cd clank
   ```

3. **Install Python Dependencies**:
   Ensure you have Python installed. Then, install the required Python libraries:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Moonshine**:
   Ensure the Moonshine model is set up and available at the specified `model_path` in the script.

## Usage

Run the main script to record and transcribe audio:

```bash
python transcribe.py
```

- **Start Recording**: Speak into your microphone.
- **Stop Recording**: Press `ENTER` to finish recording.
- The transcription will automatically appear in your terminal.

## Future Goals

### AI Integration
- Host a local LLM at `127.0.0.1:5000` to process transcriptions into actionable commands.
- Design the system to support a variety of automation tasks.

### Hardware Control
- Develop a listener service that translates LLM outputs into ESP32 GPIO actions.
- Enable control of devices like LEDs, motors, and other home/industrial equipment.

### Modular Development
- Provide users with modular options for customizing tasks and hardware actions.

## File Structure (subject to change and me forgetting temporarily to update this section)

- `transcribe.py`: Main script for recording and transcription.
- `requirements.txt`: Python dependencies (if any).
- `README.md`: Project documentation.

## Contributing

Contributions are welcome! If you'd like to help build Clank, please submit a pull request or open an issue for any feature requests or bug fixes.

## Contact

For any questions or support, reach out to me at:

- **Email**: cycloarkane@gmail.com
- **GitHub**: [cycloarcane](https://github.com/cycloarcane)

## License

This project is licensed under a modified non-commercial GNU 3.0 license.

---

Join me on this journey to make Clank a reality! 🎤🤖💡
