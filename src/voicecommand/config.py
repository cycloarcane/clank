"""Secure configuration management for Clank."""

import os
import yaml
import logging
import secrets
from pathlib import Path
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

@dataclass
class SecurityConfig:
    require_authentication: bool = True
    enable_https: bool = True
    api_key_length: int = 32
    max_requests_per_minute: int = 60
    max_audio_processing_time: int = 30
    enable_audit_logging: bool = True

@dataclass
class NetworkConfig:
    use_service_discovery: bool = True
    mdns_service_name: str = "_clank-led._tcp.local"
    fallback_timeout: float = 5.0
    connection_timeout: float = 10.0

@dataclass
class LLMConfig:
    endpoint: str = "http://127.0.0.1:11434/api/generate"
    model: str = "qwen3:14b"
    temperature: float = 0.0
    max_tokens: int = 150
    timeout: float = 30.0

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
        self.network = NetworkConfig()
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
            if 'network' in config_data:
                self._update_dataclass(self.network, config_data['network'])
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
            'CLANK_API_KEY': ('security', 'api_key'),
            'CLANK_HTTPS_CERT': ('security', 'https_cert_path'),
            'CLANK_HTTPS_KEY': ('security', 'https_key_path'),
            'CLANK_LLM_ENDPOINT': ('llm', 'endpoint'),
            'CLANK_LLM_MODEL': ('llm', 'model'),
            'CLANK_LOG_LEVEL': ('logging', 'level'),
            'CLANK_ENABLE_HTTPS': ('security', 'enable_https'),
            'CLANK_REQUIRE_AUTH': ('security', 'require_authentication'),
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
            
        # Validate security settings
        if self.security.api_key_length < 16:
            raise ValueError("API key length must be at least 16 characters")
        if self.security.max_requests_per_minute <= 0:
            raise ValueError("Max requests per minute must be positive")
            
        # Validate network settings
        if self.network.connection_timeout <= 0:
            raise ValueError("Connection timeout must be positive")
            
        # Validate LLM settings
        if self.llm.max_tokens <= 0:
            raise ValueError("Max tokens must be positive")
        if self.llm.timeout <= 0:
            raise ValueError("LLM timeout must be positive")
    
    def generate_api_key(self) -> str:
        """Generate a cryptographically secure API key."""
        return secrets.token_urlsafe(self.security.api_key_length)
    
    def get_api_key(self) -> str:
        """Get API key from environment or generate new one."""
        api_key = os.environ.get('CLANK_API_KEY')
        if not api_key:
            api_key = self.generate_api_key()
            logging.warning("No API key found in environment. Generated new key.")
            logging.info(f"Set CLANK_API_KEY environment variable to: {api_key}")
        return api_key
    
    def get_cert_paths(self) -> tuple[Optional[str], Optional[str]]:
        """Get HTTPS certificate and key paths."""
        cert_path = os.environ.get('CLANK_HTTPS_CERT')
        key_path = os.environ.get('CLANK_HTTPS_KEY')
        return cert_path, key_path
    
    def ensure_directories(self):
        """Ensure required directories exist."""
        directories = [
            os.path.dirname(self.logging.file),
            os.path.dirname(self.logging.audit_file),
            self.models.models_directory,
            'config',
            'certs'
        ]
        
        for directory in directories:
            if directory:
                os.makedirs(directory, exist_ok=True)