"""Input validation and sanitization for Clank voice commands."""

import re
import json
import logging
from typing import Dict, Any, Optional

class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass

# Canonical colour palette for the RGB strip. The validator enforces that a
# requested colour is one of these names; the control layer maps the name to
# these 8-bit (R, G, B) channel values before publishing over MQTT. Keep the
# names in sync with the colour list in the LLM system prompt.
COLOR_RGB = {
    "red":       (255,   0,   0),
    "green":     (0,   255,   0),
    "blue":      (0,     0, 255),
    "white":     (255, 255, 240),  # blue trimmed slightly — strip ran cool
    "warm white":(255, 170,  90),
    "yellow":    (255, 200,   0),
    "orange":    (255,  80,   0),
    "amber":     (255, 120,   0),
    "purple":    (140,   0, 255),
    "violet":    (140,   0, 255),
    "pink":      (255,  40, 130),
    "magenta":   (255,   0, 255),
    "cyan":      (0,   255, 255),
    "teal":      (0,   200, 160),
    "turquoise": (0,   220, 200),
    "lime":      (160, 255,   0),
    "gold":      (255, 180,   0),
}

# Spoken effect name -> WLED effect (FX) ID. IDs are WLED's own effect indices
# (from the device's /json/eff list). Limited to time-based effects that render
# meaningfully on an analog/PWM strip (one virtual pixel): the whole strip
# changes together over time. Spatial effects (wipe, chase, scanner, comet,
# meteor, fireworks, etc.) are excluded because they need addressable pixels to
# be visible — on a single analog pixel they collapse to solid or a plain blink.
# Spoken effect name -> WLED FX id. Restricted to the effects WLED actually
# offers for our single-pixel (len:1) analog RGB segment — i.e. the temporal
# effects that animate one colour zone. Spatial effects (Rainbow, Saw, Sine,
# Wipe, Chase, ...) are hidden by WLED on a 1-pixel segment because they need
# length to render, so they're deliberately NOT mapped here: sending them would
# silently do nothing. Audio-reactive effects (DJ Light, Freqwave, Waterfall,
# ...) are also omitted — the AudioReactive usermod is disabled and no mic is
# wired, so they'd never animate. IDs verified live against the device's
# /json/eff. If you ever wire an I2S mic + enable AudioReactive, the reactive
# effects can be added back.
WLED_EFFECTS = {
    # steady
    "solid":          0,
    "none":           0,
    "steady":         0,
    "off effect":     0,
    # simple on/off + brightness modulation
    "blink":          1,
    "breathe":        2,
    "pulse":          2,
    "breathing":      2,
    "fade":           12,
    "heartbeat":      100,
    "heart beat":     100,
    # colour cycling. WLED's spatial "Rainbow" (9) is dead on one pixel, so the
    # common spoken word "rainbow" maps to Colorloop (8), which cycles the hue
    # of the single zone — exactly what people mean by "rainbow" here.
    "random":         5,
    "random colors":  5,
    "random colours": 5,
    "colorloop":      8,
    "colourloop":     8,
    "color loop":     8,
    "colour loop":    8,
    "cycle":          8,
    "cycle colors":   8,
    "cycle colours":  8,
    "rainbow":        8,
    # flashing / strobe family
    "strobe":         23,
    "flash":          23,
    "strobe rainbow": 24,
    "rainbow strobe": 24,
    "strobe mega":    25,
    "mega strobe":    25,
    "blink rainbow":  26,
    "rainbow blink":  26,
    # flicker / fire
    "candle":         88,
    "flicker":        88,
    "candlelight":    88,
    "candle light":   88,
    "fire":           45,
    "fire flicker":   45,
    "flame":          45,
    # misc
    "tv":             116,
    "tv simulator":   116,
    "television":     116,
}

class CommandValidator:
    """Validates and sanitizes voice commands."""

    VALID_STATES = {"on", "off"}

    def __init__(self, registry=None):
        self.logger = logging.getLogger(__name__)
        # Device registry (voicecommand.devices.DeviceRegistry). When provided,
        # set_rgb / set_switch commands resolve their "target" to a known device
        # and the device's type is checked against the action. When None (e.g.
        # in unit tests), target is passed through unresolved.
        self.registry = registry

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
        valid_actions = ["set_rgb", "set_switch", "unknown"]
        if action not in valid_actions:
            raise ValidationError(f"Invalid action: {action}. Must be one of {valid_actions}")

        # Validate RGB-strip parameters
        if action == "set_rgb":
            if "parameters" not in data:
                raise ValidationError("set_rgb action requires parameters")

            params = data["parameters"]
            if not isinstance(params, dict):
                raise ValidationError("Parameters must be an object")

            result = self._validate_rgb_parameters(params)
            result["target"] = self._resolve_target(action, data.get("target"))
            return result

        # Validate on/off smart-plug parameters
        if action == "set_switch":
            if "parameters" not in data:
                raise ValidationError("set_switch action requires parameters")

            params = data["parameters"]
            if not isinstance(params, dict):
                raise ValidationError("Parameters must be an object")

            result = self._validate_switch_parameters(params)
            result["target"] = self._resolve_target(action, data.get("target"))
            return result

        # For unknown actions, just ensure no dangerous parameters
        elif action == "unknown":
            if "parameters" in data:
                self._validate_safe_parameters(data["parameters"])

        return data
    
    def _validate_rgb_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate set_rgb parameters (any of colour / on-off state / brightness).

        All three are optional, but at least one must be present. Colour must be
        a known palette name; brightness is a 0-100 percentage."""
        validated: Dict[str, Any] = {}

        color = params.get("color")
        if color is not None:
            if not isinstance(color, str):
                raise ValidationError("color must be a string")
            color = color.lower().strip()
            if color not in COLOR_RGB:
                raise ValidationError(
                    f"Invalid color: {color}. Must be one of {sorted(COLOR_RGB)}"
                )
            validated["color"] = color

        state = params.get("state")
        if state is not None:
            if not isinstance(state, str):
                raise ValidationError("state must be a string")
            state = state.lower().strip()
            if state not in self.VALID_STATES:
                raise ValidationError(
                    f"Invalid state: {state}. Must be one of {sorted(self.VALID_STATES)}"
                )
            validated["state"] = state

        brightness = params.get("brightness")
        if brightness is not None:
            if not isinstance(brightness, (int, float)) or isinstance(brightness, bool):
                raise ValidationError("brightness must be a number")
            brightness = int(brightness)
            if brightness < 0 or brightness > 100:
                raise ValidationError("brightness must be between 0 and 100")
            validated["brightness"] = brightness

        effect = params.get("effect")
        if effect is not None:
            if not isinstance(effect, str):
                raise ValidationError("effect must be a string")
            effect = effect.lower().strip()
            if effect not in WLED_EFFECTS:
                raise ValidationError(
                    f"Invalid effect: {effect}. Must be one of {sorted(WLED_EFFECTS)}"
                )
            validated["effect"] = effect

        # speed and intensity are 0-100 percentages controlling the active
        # effect's animation (e.g. how fast a strobe flashes). They apply to
        # whatever effect is running, so they're valid on their own.
        for key in ("speed", "intensity"):
            value = params.get(key)
            if value is not None:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValidationError(f"{key} must be a number")
                value = int(value)
                if value < 0 or value > 100:
                    raise ValidationError(f"{key} must be between 0 and 100")
                validated[key] = value

        if not validated:
            raise ValidationError(
                "set_rgb requires at least one of color, state, brightness, "
                "effect, speed, or intensity"
            )
        return {"action": "set_rgb", "parameters": validated}

    def _validate_switch_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate set_switch parameters (just an on/off state)."""
        state = params.get("state")
        if not isinstance(state, str):
            raise ValidationError("state must be a string")
        state = state.lower().strip()
        if state not in self.VALID_STATES:
            raise ValidationError(
                f"Invalid state: {state}. Must be one of {sorted(self.VALID_STATES)}"
            )
        return {"action": "set_switch", "parameters": {"state": state}}

    def _resolve_target(self, action: str, target: Any) -> Optional[str]:
        """Resolve a command's target to a known device's canonical name.

        With no registry (unit tests) the raw target string is passed through.
        With a registry, the target must resolve to a device whose type the
        action can drive (e.g. set_switch -> a switch); an unknown or
        type-mismatched target is rejected so a misheard name never fires the
        wrong device.
        """
        if target is not None and not isinstance(target, str):
            raise ValidationError("target must be a string")
        if self.registry is None:
            return target.lower().strip() if isinstance(target, str) else None

        from voicecommand.devices import ACTION_TYPES
        kind = ACTION_TYPES.get(action)
        device = self.registry.resolve(target, kind)
        if device is None:
            named = f"{target!r}" if target else "(no target given)"
            raise ValidationError(
                f"Could not resolve target {named} to a configured device for "
                f"{action}. Known devices: "
                f"{sorted(d.name for d in self.registry.devices)}"
            )
        if kind and device.type not in kind:
            raise ValidationError(
                f"Device {device.name!r} ({device.type}) cannot handle {action}"
            )
        return device.name

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
