"""Secure configuration management for Clank."""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class AudioConfig:
    sampling_rate: int = 16000
    chunk_size: int = 512
    lookback_chunks: int = 5
    max_speech_seconds: int = 15
    min_refresh_seconds: float = 0.2
    vad_threshold: float = 0.5
    min_silence_duration_ms: int = 300
    # Capture device passed to PortAudio (sounddevice). Empty = the OS default
    # input (current behaviour). Set to a device index, a name substring (e.g.
    # "USB"), or a host-API name ("pulse") to pin Clank to a specific mic —
    # `python -m sounddevice` lists the options. See docs/multi-mic.md for the
    # PipeWire two-mic combine setup that uses input_device: "pulse".
    input_device: str = ""
    # Wake word: utterances that don't begin with (a near-match of) this word
    # are discarded without being sent to the LLM, logged, or retained. Set
    # require_wake_word False to act on every utterance (less private).
    wake_word: str = "clank"
    require_wake_word: bool = True
    # Wake detection engine:
    #   "text"        — transcribe every utterance, then match the wake_word in
    #                   the transcript (simple, but STT runs constantly).
    #   "openwakeword"— a small acoustic model gates BEFORE transcription, so
    #                   Moonshine stays idle until the wake word fires.
    wake_engine: str = "openwakeword"
    # openWakeWord settings (only used when wake_engine == "openwakeword").
    # oww_model: a builtin name ("hey_jarvis", "alexa", "hey_mycroft",
    # "hey_marvin") or a path to a custom-trained .onnx model. Defaults to our
    # locally-trained "hey clank" model (hash-pinned in voice_LED_control.py).
    oww_model: str = "models/wakeword/hey_clank.onnx"
    # 0.3 is deliberately sensitive: "hey clank" is a rare two-word phrase, so we
    # optimise for recall (the trained model sits at ~0.09 false positives/hour,
    # leaving plenty of headroom). Raise toward 0.5 if you get false triggers.
    oww_threshold: float = 0.3
    # Max seconds to wait for a command after the wake word fires.
    command_timeout_s: float = 6.0
    # Pre-roll: seconds of audio kept before the wake word fires and prepended
    # to the captured command, so a fast command onset (e.g. "all") isn't
    # clipped by wake-detection latency.
    command_preroll_s: float = 0.5
    # Debug: log the peak wake-word score once a second so you can see whether
    # audio is reaching the model and how high it scores when you speak.
    oww_debug: bool = False

@dataclass
class SecurityConfig:
    # Privacy: when False (default), raw transcripts are NEVER logged or
    # persisted — only resolved commands are recorded, so non-command speech
    # leaves no trace. Set True only for debugging.
    log_transcripts: bool = False

@dataclass
class MqttConfig:
    # The broker runs on this PC (also the host hotspot gateway), so the
    # Python side connects over loopback. The ESP32 reaches the same broker at
    # the hotspot address 10.42.0.1. Credentials come from the environment
    # (MQTT_USER / MQTT_PASS), never the config file.
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    rgb_set_topic: str = "wled/clank/api"
    # After each command, snapshot the resulting look into this WLED preset slot
    # so a mains power-cycle restores it (the device boots into this slot via
    # its def.ps setting) instead of the factory amber default. Set to 0 to
    # disable and avoid a flash write per command.
    persist_preset: int = 1

@dataclass
class LLMConfig:
    endpoint: str = "http://127.0.0.1:11434/api/generate"
    model: str = "qwen3:4b"
    temperature: float = 0.0
    max_tokens: int = 150
    timeout: float = 90.0
    # Force Ollama to emit a single valid JSON object (structured output).
    response_format: str = "json"
    # Disable reasoning models' "thinking" so the token budget produces the
    # answer, not hidden reasoning. Required for the qwen3 family via Ollama.
    # Set to null in config for models that do not support a think parameter.
    think: Optional[bool] = False

@dataclass
class ModelConfig:
    moonshine_commit: str = "2501abf"
    verify_checksums: bool = True
    models_directory: str = "models/moonshine"

@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/clank.log"
    max_size_mb: int = 10
    backup_count: int = 5
    audit_file: str = "logs/audit.log"

class ClankConfig:
    """Secure configuration manager for Clank."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._find_config_file()
        self.audio = AudioConfig()
        self.security = SecurityConfig()
        self.mqtt = MqttConfig()
        self.llm = LLMConfig()
        self.models = ModelConfig()
        self.logging = LoggingConfig()
        
        # Load configuration
        self._load_config()
        self._load_environment_overrides()
        self._validate_config()
        
    def _find_config_file(self) -> str:
        """Find configuration file in standard locations."""
        possible_paths = [
            os.environ.get('CLANK_CONFIG'),
            'config/default.yaml',
            os.path.expanduser('~/.config/clank/config.yaml'),
            '/etc/clank/config.yaml'
        ]
        
        for path in possible_paths:
            if path and os.path.exists(path):
                return path
                
        # Return default path if none found
        return 'config/default.yaml'
    
    def _load_config(self):
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_path):
            logging.warning(f"Config file not found: {self.config_path}, using defaults")
            return
            
        try:
            with open(self.config_path, 'r') as f:
                config_data = yaml.safe_load(f) or {}
                
            # Update configuration objects
            if 'audio' in config_data:
                self._update_dataclass(self.audio, config_data['audio'])
            if 'security' in config_data:
                self._update_dataclass(self.security, config_data['security'])
            if 'mqtt' in config_data:
                self._update_dataclass(self.mqtt, config_data['mqtt'])
            if 'llm' in config_data:
                self._update_dataclass(self.llm, config_data['llm'])
            if 'models' in config_data:
                self._update_dataclass(self.models, config_data['models'])
            if 'logging' in config_data:
                self._update_dataclass(self.logging, config_data['logging'])
                
        except Exception as e:
            logging.error(f"Error loading config file {self.config_path}: {e}")
            raise
    
    def _update_dataclass(self, obj, data: Dict[str, Any]):
        """Update dataclass object with dictionary data."""
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
    
    def _load_environment_overrides(self):
        """Load configuration overrides from environment variables."""
        env_mappings = {
            'CLANK_LLM_ENDPOINT': ('llm', 'endpoint'),
            'CLANK_LLM_MODEL': ('llm', 'model'),
            'CLANK_LOG_LEVEL': ('logging', 'level'),
        }
        
        for env_var, (section, key) in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                section_obj = getattr(self, section)
                # Convert string boolean values
                if isinstance(getattr(section_obj, key, None), bool):
                    value = value.lower() in ('true', '1', 'yes', 'on')
                setattr(section_obj, key, value)
    
    def _validate_config(self):
        """Validate configuration values."""
        # Validate audio settings
        if self.audio.sampling_rate <= 0:
            raise ValueError("Audio sampling rate must be positive")
        if self.audio.max_speech_seconds <= 0:
            raise ValueError("Max speech seconds must be positive")

        # Validate LLM settings
        if self.llm.max_tokens <= 0:
            raise ValueError("Max tokens must be positive")
        if self.llm.timeout <= 0:
            raise ValueError("LLM timeout must be positive")

    def ensure_directories(self):
        """Ensure required directories exist."""
        directories = [
            os.path.dirname(self.logging.file),
            os.path.dirname(self.logging.audit_file),
            self.models.models_directory,
            'config',
        ]
        
        for directory in directories:
            if directory:
                os.makedirs(directory, exist_ok=True)