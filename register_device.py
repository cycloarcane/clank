#!/usr/bin/env python3
"""Device registration helper for Clank."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from voicecommand.auth import AuthManager

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 register_device.py <device_name>")
        sys.exit(1)
    
    device_name = sys.argv[1]
    auth_manager = AuthManager()
    device_id, api_key = auth_manager.register_device(device_name)
    
    print(f"Device registered successfully!")
    print(f"Device ID: {device_id}")
    print(f"API Key: {api_key}")
    print("\nAdd this to your ESP32 configuration:")
    print(f"const char* API_KEY = \"{api_key}\";")

if __name__ == "__main__":
    main()
