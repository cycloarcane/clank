"""Authentication and authorization system for Clank."""

import hashlib
import hmac
import time
import secrets
import logging
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
from threading import Lock
import json
import os

@dataclass
class Device:
    """Represents an authenticated device."""
    device_id: str
    api_key: str
    name: str
    created_at: float
    last_seen: float = field(default_factory=time.time)
    is_active: bool = True

class RateLimiter:
    """Simple token bucket rate limiter."""
    
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = {}
        self.lock = Lock()
    
    def allow_request(self, identifier: str) -> bool:
        """Check if request is allowed under rate limit."""
        now = time.time()
        window_start = now - self.window_seconds
        
        with self.lock:
            if identifier not in self.requests:
                self.requests[identifier] = []
            
            # Remove old requests outside the window
            self.requests[identifier] = [
                req_time for req_time in self.requests[identifier] 
                if req_time > window_start
            ]
            
            # Check if under limit
            if len(self.requests[identifier]) >= self.max_requests:
                return False
            
            # Add current request
            self.requests[identifier].append(now)
            return True

class AuthManager:
    """Manages authentication and device registration."""
    
    def __init__(self, devices_file: str = "config/devices.json"):
        self.devices_file = devices_file
        self.devices: Dict[str, Device] = {}
        self.api_keys: Dict[str, str] = {}  # api_key -> device_id
        self.rate_limiter = RateLimiter(max_requests=60)  # 60 requests per minute
        self.lock = Lock()
        self.logger = logging.getLogger(__name__)
        
        self._load_devices()
    
    def _load_devices(self):
        """Load devices from persistent storage."""
        if not os.path.exists(self.devices_file):
            self.logger.info("No devices file found, starting with empty device list")
            return
        
        try:
            with open(self.devices_file, 'r') as f:
                data = json.load(f)
            
            for device_data in data.get('devices', []):
                device = Device(**device_data)
                self.devices[device.device_id] = device
                self.api_keys[device.api_key] = device.device_id
                
            self.logger.info(f"Loaded {len(self.devices)} devices")
            
        except Exception as e:
            self.logger.error(f"Error loading devices file: {e}")
    
    def _save_devices(self):
        """Save devices to persistent storage."""
        os.makedirs(os.path.dirname(self.devices_file), exist_ok=True)
        
        try:
            data = {
                'devices': [
                    {
                        'device_id': device.device_id,
                        'api_key': device.api_key,
                        'name': device.name,
                        'created_at': device.created_at,
                        'last_seen': device.last_seen,
                        'is_active': device.is_active
                    }
                    for device in self.devices.values()
                ]
            }
            
            with open(self.devices_file, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Error saving devices file: {e}")
    
    def register_device(self, device_name: str) -> tuple[str, str]:
        """Register a new device and return device_id and api_key."""
        device_id = f"device_{secrets.token_urlsafe(16)}"
        api_key = secrets.token_urlsafe(32)
        
        device = Device(
            device_id=device_id,
            api_key=api_key,
            name=device_name,
            created_at=time.time()
        )
        
        with self.lock:
            self.devices[device_id] = device
            self.api_keys[api_key] = device_id
            self._save_devices()
        
        self.logger.info(f"Registered new device: {device_name} ({device_id})")
        return device_id, api_key
    
    def authenticate(self, api_key: str, client_ip: str = "unknown") -> Optional[Device]:
        """Authenticate a request using API key."""
        # Rate limiting check
        if not self.rate_limiter.allow_request(client_ip):
            self.logger.warning(f"Rate limit exceeded for {client_ip}")
            return None
        
        # API key validation
        if api_key not in self.api_keys:
            self.logger.warning(f"Invalid API key from {client_ip}")
            return None
        
        device_id = self.api_keys[api_key]
        device = self.devices.get(device_id)
        
        if not device or not device.is_active:
            self.logger.warning(f"Inactive device {device_id} attempted access from {client_ip}")
            return None
        
        # Update last seen inside the lock to prevent concurrent writes
        with self.lock:
            device.last_seen = time.time()
            self._save_devices()

        self.logger.info(f"Authenticated device {device.name} ({device_id}) from {client_ip}")
        return device
    
    def revoke_device(self, device_id: str) -> bool:
        """Revoke access for a device."""
        with self.lock:
            if device_id not in self.devices:
                return False
            
            device = self.devices[device_id]
            device.is_active = False
            
            # Remove from API key lookup
            if device.api_key in self.api_keys:
                del self.api_keys[device.api_key]
            
            self._save_devices()
        
        self.logger.info(f"Revoked device {device_id}")
        return True
    
    def list_devices(self) -> list[Device]:
        """List all registered devices."""
        return list(self.devices.values())
    
    def cleanup_inactive_devices(self, max_age_days: int = 30):
        """Remove devices that haven't been seen for a long time."""
        cutoff_time = time.time() - (max_age_days * 24 * 3600)
        inactive_devices = []
        
        with self.lock:
            for device_id, device in list(self.devices.items()):
                if device.last_seen < cutoff_time and not device.is_active:
                    inactive_devices.append(device_id)
                    del self.devices[device_id]
                    if device.api_key in self.api_keys:
                        del self.api_keys[device.api_key]
            
            if inactive_devices:
                self._save_devices()
        
        if inactive_devices:
            self.logger.info(f"Cleaned up {len(inactive_devices)} inactive devices")
        
        return inactive_devices

def validate_api_key_format(api_key: str) -> bool:
    """Validate API key format."""
    if not api_key or not isinstance(api_key, str):
        return False
    
    # Should be URL-safe base64 encoded, typically 32+ characters
    if len(api_key) < 16:
        return False
    
    # Should only contain valid URL-safe base64 characters
    valid_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_')
    return all(c in valid_chars for c in api_key)

def create_secure_hash(data: str, salt: str = None) -> str:
    """Create a secure hash of data with optional salt."""
    if salt is None:
        salt = secrets.token_urlsafe(16)
    
    # Use PBKDF2 for key derivation
    hash_bytes = hashlib.pbkdf2_hmac(
        'sha256',
        data.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # iterations
    )
    
    return f"{salt}${hash_bytes.hex()}"

def verify_secure_hash(data: str, hash_str: str) -> bool:
    """Verify data against a secure hash."""
    try:
        salt, hash_hex = hash_str.split('$', 1)
        expected_hash = create_secure_hash(data, salt)
        return hmac.compare_digest(hash_str, expected_hash)
    except (ValueError, AttributeError):
        return False