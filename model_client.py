import requests
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class ModelResponse:
    text: str
    model: str
    total_tokens: int
    finish_reason: Optional[str] = None

class ModelClient:
    def __init__(self):
        self.base_url = "http://127.0.0.1:5000"
    
    def _get_nested_value(self, obj: dict, path: str) -> Optional[any]:
        """Helper method to get nested dictionary values using a path string."""
        try:
            current = obj
            parts = path.replace("][", "].").replace("[", ".").replace("]", "").split(".")
            for part in parts:
                if part.isdigit():
                    current = current[int(part)]
                else:
                    current = current[part]
            return current
        except (KeyError, IndexError, TypeError) as e:
            logging.error(f"Failed to access path '{path}' in object: {e}")
            return None

    def get_completion(self, transcription) -> ModelResponse:
        """Send text to local model endpoint and get response."""
        try:
            headers = {
                "Content-Type": "application/json"
            }
            
            # Use the first element if it's a list
            prompt = transcription[0] if isinstance(transcription, list) else transcription
            
            data = {
                "prompt": prompt,
                "max_tokens": 500,
                "temperature": 0.7,
                "stream": False,
                "stop": None
            }
            
            response = requests.post(
                f"{self.base_url}/v1/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            text = self._get_nested_value(result, "choices[0].text")
            if text is None:
                raise ValueError("No text found in response")
                
            model_response = ModelResponse(
                text=text,
                model=self._get_nested_value(result, "model") or "unknown",
                total_tokens=self._get_nested_value(result, "usage.total_tokens") or 0,
                finish_reason=self._get_nested_value(result, "choices[0].finish_reason")
            )
            
            return model_response
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed: {e}")
            raise Exception(f"Model API error: {e}")
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            raise
