"""Input validation and sanitization for Clank voice commands."""

import re
import json
import logging
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from enum import Enum

class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass

class LEDColor(Enum):
    """Valid LED colors."""
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    ALL = "all"

class LEDState(Enum):
    """Valid LED states."""
    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"

@dataclass
class LEDCommand:
    """Validated LED command structure."""
    action: str
    color: Optional[str] = None
    state: Optional[str] = None
    brightness: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"action": self.action}
        if self.action == "led_control":
            result["parameters"] = {}
            if self.color is not None:
                result["parameters"]["color"] = self.color
            if self.state is not None:
                result["parameters"]["state"] = self.state
            if self.brightness is not None:
                result["parameters"]["brightness"] = self.brightness
        return result

class CommandValidator:
    """Validates and sanitizes voice commands."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Patterns for malicious content detection
        self.malicious_patterns = [
            r'<script[^>]*>',  # Script tags
            r'javascript:',     # JavaScript protocol
            r'data:.*base64',   # Data URLs with base64
            r'on\w+\s*=',      # Event handlers
            r'eval\s*\(',      # Eval function
            r'exec\s*\(',      # Exec function
            r'import\s+',      # Import statements
            r'__.*__',         # Python magic methods
            r'subprocess',     # Subprocess module
            r'os\.',           # OS module access
            r'file://',        # File protocol
        ]
        
        # Compile patterns for performance
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.malicious_patterns]
    
    def sanitize_text(self, text: str, max_length: int = 500) -> str:
        """Sanitize input text by removing potentially dangerous content."""
        if not isinstance(text, str):
            raise ValidationError("Input must be a string")
        
        # Length check
        if len(text) > max_length:
            self.logger.warning(f"Input text truncated from {len(text)} to {max_length} characters")
            text = text[:max_length]
        
        # Remove null bytes and control characters
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\t\n\r')
        
        # Check for malicious patterns
        for pattern in self.compiled_patterns:
            if pattern.search(text):
                self.logger.warning(f"Malicious pattern detected in input: {pattern.pattern}")
                raise ValidationError("Input contains potentially malicious content")
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def validate_json_structure(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate JSON command structure."""
        if not isinstance(data, dict):
            raise ValidationError("Command must be a JSON object")
        
        # Required fields
        if "action" not in data:
            raise ValidationError("Missing required field: action")
        
        action = data["action"]
        if not isinstance(action, str):
            raise ValidationError("Action must be a string")
        
        # Validate action type
        valid_actions = ["led_control", "unknown"]
        if action not in valid_actions:
            raise ValidationError(f"Invalid action: {action}. Must be one of {valid_actions}")
        
        # Validate LED control parameters
        if action == "led_control":
            if "parameters" not in data:
                raise ValidationError("LED control action requires parameters")
            
            params = data["parameters"]
            if not isinstance(params, dict):
                raise ValidationError("Parameters must be an object")
            
            return self._validate_led_parameters(params, data)
        
        # For unknown actions, just ensure no dangerous parameters
        elif action == "unknown":
            if "parameters" in data:
                self._validate_safe_parameters(data["parameters"])
        
        return data
    
    def _validate_led_parameters(self, params: Dict[str, Any], full_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate LED control parameters."""
        validated_params = {}
        
        # Validate color
        if "color" in params:
            color = params["color"]
            if color is not None:
                if not isinstance(color, str):
                    raise ValidationError("Color must be a string")
                
                color = color.lower().strip()
                try:
                    # Validate against enum
                    LEDColor(color)
                    validated_params["color"] = color
                except ValueError:
                    raise ValidationError(f"Invalid color: {color}. Must be one of {[c.value for c in LEDColor]}")
        
        # Validate state
        if "state" in params:
            state = params["state"]
            if state is not None:
                if not isinstance(state, str):
                    raise ValidationError("State must be a string")
                
                state = state.lower().strip()
                try:
                    # Validate against enum
                    LEDState(state)
                    validated_params["state"] = state
                except ValueError:
                    raise ValidationError(f"Invalid state: {state}. Must be one of {[s.value for s in LEDState]}")
        
        # Validate brightness
        if "brightness" in params:
            brightness = params["brightness"]
            if brightness is not None:
                if not isinstance(brightness, (int, float)):
                    raise ValidationError("Brightness must be a number")
                
                brightness = int(brightness)
                if brightness < 0 or brightness > 100:
                    raise ValidationError("Brightness must be between 0 and 100")
                
                validated_params["brightness"] = brightness
        
        # Ensure at least one parameter is provided
        if not validated_params:
            raise ValidationError("LED control requires at least one parameter (color, state, or brightness)")
        
        # Return validated structure
        return {
            "action": "led_control",
            "parameters": validated_params
        }
    
    def _validate_safe_parameters(self, params: Any):
        """Ensure parameters don't contain dangerous content."""
        if isinstance(params, dict):
            for key, value in params.items():
                if isinstance(key, str):
                    self.sanitize_text(key, max_length=50)
                if isinstance(value, str):
                    self.sanitize_text(value, max_length=100)
                elif isinstance(value, (dict, list)):
                    self._validate_safe_parameters(value)
        elif isinstance(params, list):
            for item in params:
                if isinstance(item, str):
                    self.sanitize_text(item, max_length=100)
                elif isinstance(item, (dict, list)):
                    self._validate_safe_parameters(item)
    
    def validate_transcription(self, text: str) -> str:
        """Validate and sanitize transcribed text."""
        if not text:
            raise ValidationError("Empty transcription")
        
        # Sanitize the text
        sanitized = self.sanitize_text(text, max_length=200)
        
        # Additional checks for voice commands
        if len(sanitized.split()) > 20:
            raise ValidationError("Command too long (max 20 words)")
        
        return sanitized
    
    def validate_llm_response(self, response_text: str) -> Dict[str, Any]:
        """Validate LLM response and extract JSON."""
        if not response_text:
            raise ValidationError("Empty LLM response")
        
        # Sanitize the response
        sanitized = self.sanitize_text(response_text, max_length=1000)
        
        # Extract JSON from response
        json_data = self._extract_json_from_text(sanitized)
        if not json_data:
            self.logger.warning(f"No valid JSON found in LLM response: {sanitized[:100]}...")
            return {"action": "unknown", "parameters": {}}
        
        # Validate the JSON structure
        return self.validate_json_structure(json_data)
    
    def _extract_json_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract the first valid JSON object from text."""
        try:
            # Find the first { and last } in the text
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end + 1]
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass
        return None
    
    def create_led_command(self, color: str = None, state: str = None, brightness: int = None) -> LEDCommand:
        """Create a validated LED command."""
        # Validate inputs
        validated_data = {
            "action": "led_control",
            "parameters": {}
        }
        
        if color is not None:
            validated_data["parameters"]["color"] = color
        if state is not None:
            validated_data["parameters"]["state"] = state
        if brightness is not None:
            validated_data["parameters"]["brightness"] = brightness
        
        # Validate the complete structure
        validated = self.validate_json_structure(validated_data)
        
        return LEDCommand(
            action=validated["action"],
            color=validated["parameters"].get("color"),
            state=validated["parameters"].get("state"),
            brightness=validated["parameters"].get("brightness")
        )

def validate_esp32_response(response_text: str) -> bool:
    """Validate ESP32 response for security."""
    if not isinstance(response_text, str):
        return False
    
    # Check length
    if len(response_text) > 1000:
        return False
    
    # Should be simple status messages
    allowed_patterns = [
        r'^Command processed$',
        r'^Invalid JSON$',
        r'^Unknown action$',
        r'^No data received$',
        r'^Device registered$',
        r'^Authentication failed$'
    ]
    
    return any(re.match(pattern, response_text) for pattern in allowed_patterns)