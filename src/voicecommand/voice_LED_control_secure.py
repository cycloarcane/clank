#!/usr/bin/env python3
"""Security-hardened voice control system for Clank LED assistant."""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from voicecommand.config import ClankConfig
from voicecommand.auth import AuthManager
from voicecommand.validation import CommandValidator
from voicecommand.discovery import create_discovery_service
from voicecommand.secure_logging import setup_secure_logging

def main():
    parser = argparse.ArgumentParser(description="Clank Security-Hardened Voice Assistant")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--discover", action="store_true", help="Run device discovery only")
    parser.add_argument("--register-device", help="Register a new device")
    args = parser.parse_args()
    
    try:
        # Load configuration
        config = ClankConfig(args.config)
        config.ensure_directories()
        
        # Setup logging
        logger, audit_logger, error_handler = setup_secure_logging(config)
        logger.info("Starting Clank Security-Hardened Voice Assistant")
        
        # Device registration mode
        if args.register_device:
            auth_manager = AuthManager()
            device_id, api_key = auth_manager.register_device(args.register_device)
            print(f"Device registered: {args.register_device}")
            print(f"Device ID: {device_id}")
            print(f"API Key: {api_key}")
            return
        
        # Discovery mode
        if args.discover:
            discovery = create_discovery_service(config)
            discovery.start_discovery()
            print("Discovering devices... Press Ctrl+C to stop")
            try:
                while True:
                    devices = discovery.get_devices()
                    print(f"Found {len(devices)} devices:")
                    for device in devices:
                        print(f"  - {device.name}: {device.endpoint}")
                    import time
                    time.sleep(5)
            except KeyboardInterrupt:
                discovery.stop_discovery()
            return
        
        # Normal operation
        print("Clank security-hardened voice assistant")
        print("Configuration loaded from:", config.config_path)
        print("Authentication required:", config.security.require_authentication)
        print("HTTPS enabled:", config.security.enable_https)
        print("\nPress Ctrl+C to stop")
        
        # TODO: Implement the secure voice processing loop
        print("Secure voice processing not yet implemented.")
        print("This is the security-hardened framework.")
        
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
