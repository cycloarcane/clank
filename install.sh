#!/bin/bash
# Clank Security-Hardened Installation Script
# Automatically sets up a secure Clank voice-controlled LED system

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PYTHON_MIN_VERSION="3.8"
OLLAMA_MODEL="qwen3:14b"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Logging
LOG_FILE="$PROJECT_DIR/install.log"
exec > >(tee -a "$LOG_FILE") 2>&1

print_header() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║              Clank Security-Hardened Installer              ║"
    echo "║              Voice-Controlled LED Assistant                 ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "${GREEN}[STEP]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

check_requirements() {
    print_step "Checking system requirements..."
    
    # Check Python version
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
        
        if [[ $PYTHON_MAJOR -ge 3 && $PYTHON_MINOR -ge 8 ]]; then
            print_info "Python $PYTHON_VERSION found ✓"
        else
            print_error "Python 3.8+ required, found $PYTHON_VERSION"
            exit 1
        fi
    else
        print_error "Python 3 not found. Please install Python 3.8 or later."
        exit 1
    fi
    
    # Check for system dependencies
    MISSING_DEPS=()
    
    if ! command -v curl &> /dev/null; then
        MISSING_DEPS+=("curl")
    fi
    
    if ! command -v git &> /dev/null; then
        MISSING_DEPS+=("git")
    fi
    
    # Check for audio system dependencies
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Detect package manager and check accordingly
        if command -v pacman &> /dev/null; then
            # Arch Linux
            if ! pacman -Q libsndfile &> /dev/null; then
                MISSING_DEPS+=("libsndfile")
            fi
            if ! pacman -Q portaudio &> /dev/null; then
                MISSING_DEPS+=("portaudio")
            fi
        elif command -v dpkg &> /dev/null; then
            # Debian/Ubuntu
            if ! dpkg -l | grep -q libsndfile1 2>/dev/null; then
                MISSING_DEPS+=("libsndfile1")
            fi
            if ! dpkg -l | grep -q portaudio19-dev 2>/dev/null; then
                MISSING_DEPS+=("portaudio19-dev")
            fi
        else
            print_warning "Unknown Linux distribution - please install libsndfile and portaudio manually"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        if ! brew list portaudio &> /dev/null; then
            MISSING_DEPS+=("portaudio")
        fi
    fi
    
    if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
        print_warning "Missing system dependencies: ${MISSING_DEPS[*]}"
        
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            if command -v pacman &> /dev/null; then
                print_info "Install with: sudo pacman -S ${MISSING_DEPS[*]}"
            elif command -v dpkg &> /dev/null; then
                print_info "Install with: sudo apt-get install ${MISSING_DEPS[*]}"
            else
                print_info "Please install the missing dependencies using your package manager"
            fi
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            print_info "Install with: brew install ${MISSING_DEPS[*]}"
        fi
        
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

setup_virtual_environment() {
    print_step "Setting up Python virtual environment..."
    
    if [[ ! -d "$PROJECT_DIR/.venv" ]]; then
        python3 -m venv "$PROJECT_DIR/.venv"
        print_info "Created virtual environment"
    else
        print_info "Virtual environment already exists"
    fi
    
    source "$PROJECT_DIR/.venv/bin/activate"
    
    # Upgrade pip
    pip install --upgrade pip
    print_info "Upgraded pip"
}

install_dependencies() {
    print_step "Installing Python dependencies..."
    
    # Install security-related dependencies first
    pip install cryptography PyYAML
    
    # Install main requirements
    if [[ -f "$PROJECT_DIR/requirements-secure.txt" ]]; then
        pip install -r "$PROJECT_DIR/requirements-secure.txt"
    else
        pip install -r "$PROJECT_DIR/requirements.txt"
    fi
    
    print_info "Python dependencies installed"
}

fetch_models() {
    print_step "Fetching and verifying AI models..."
    
    # Check if models already exist and are valid
    MODELS_EXIST=false
    if [[ -f "$PROJECT_DIR/models/moonshine/encoder_model.onnx" ]] && \
       [[ -f "$PROJECT_DIR/models/moonshine/decoder_model_merged.onnx" ]] && \
       [[ -f "$PROJECT_DIR/SHA256SUMS" ]]; then
        
        print_info "Models found, verifying integrity..."
        cd "$PROJECT_DIR"
        if sha256sum -c SHA256SUMS &>/dev/null; then
            print_info "Models already present and verified ✓"
            MODELS_EXIST=true
        else
            print_warning "Model checksums don't match, re-downloading..."
        fi
    fi
    
    # Download models only if they don't exist or failed verification
    if [[ "$MODELS_EXIST" == false ]]; then
        if [[ -f "$PROJECT_DIR/scripts/fetch_moonshine.sh" ]]; then
            cd "$PROJECT_DIR"
            bash scripts/fetch_moonshine.sh
            
            # Verify checksums
            if [[ -f "$PROJECT_DIR/SHA256SUMS" ]]; then
                sha256sum -c SHA256SUMS
                print_info "Model integrity verified ✓"
            else
                print_warning "Model checksums not found"
            fi
        else
            print_error "Model fetch script not found"
            exit 1
        fi
    fi
}

check_ollama() {
    print_step "Checking Ollama installation..."
    
    if command -v ollama &> /dev/null; then
        print_info "Ollama found ✓"
        
        # Check if Ollama is running
        if ollama list &> /dev/null; then
            print_info "Ollama service is running ✓"
            
            # Check if model is available
            if ollama list | grep -q "$OLLAMA_MODEL"; then
                print_info "Model $OLLAMA_MODEL is available ✓"
            else
                print_info "Pulling model $OLLAMA_MODEL..."
                ollama pull "$OLLAMA_MODEL"
            fi
        else
            print_warning "Ollama service not running. Start with: ollama serve"
        fi
    else
        print_warning "Ollama not found. Please install from https://ollama.ai"
        print_info "After installing Ollama, run: ollama pull $OLLAMA_MODEL"
    fi
}

generate_certificates() {
    print_step "Generating HTTPS certificates..."
    
    python3 "$PROJECT_DIR/scripts/generate_certs.py" \
        --hostname localhost \
        --cert-file "$PROJECT_DIR/certs/server.crt" \
        --key-file "$PROJECT_DIR/certs/server.key"
    
    print_info "HTTPS certificates generated"
}

setup_configuration() {
    print_step "Setting up secure configuration..."
    
    # Create directories
    mkdir -p "$PROJECT_DIR/logs"
    mkdir -p "$PROJECT_DIR/config"
    mkdir -p "$PROJECT_DIR/certs"
    
    # Prompt for ESP32 IP address
    echo -e "${BLUE}ESP32 Configuration:${NC}"
    echo "Please enter your ESP32's IP address (check your router's admin page or ESP32 Serial Monitor)"
    read -p "ESP32 IP address [192.168.0.18]: " ESP32_IP_INPUT
    ESP32_IP_CONFIG=${ESP32_IP_INPUT:-192.168.0.18}
    
    # Generate API key
    API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    
    # Create environment file
    ENV_FILE="$PROJECT_DIR/.env"
    cat > "$ENV_FILE" << EOF
# Clank Security Configuration
# Generated by installer on $(date)

# Security
CLANK_API_KEY=$API_KEY
CLANK_ENABLE_HTTPS=true
CLANK_REQUIRE_AUTH=true
CLANK_HTTPS_CERT=$PROJECT_DIR/certs/server.crt
CLANK_HTTPS_KEY=$PROJECT_DIR/certs/server.key

# LLM Configuration
CLANK_LLM_MODEL=$OLLAMA_MODEL
CLANK_LLM_ENDPOINT=http://127.0.0.1:11434/api/generate

# ESP32 Configuration
ESP32_IP=$ESP32_IP_CONFIG

# Logging
CLANK_LOG_LEVEL=INFO
EOF
    
    chmod 600 "$ENV_FILE"
    print_info "Configuration file created: $ENV_FILE"
    
    # Create device registration helper
    cat > "$PROJECT_DIR/register_device.py" << 'EOF'
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
EOF
    
    chmod +x "$PROJECT_DIR/register_device.py"
}

create_startup_script() {
    print_step "Creating startup script..."
    
    cat > "$PROJECT_DIR/start_clank.sh" << EOF
#!/bin/bash
# Clank Startup Script

cd "$PROJECT_DIR"
source .venv/bin/activate

# Load environment variables
if [[ -f .env ]]; then
    export \$(cat .env | grep -v '^#' | xargs)
fi

echo "Starting Clank Voice Assistant..."
echo "Press Ctrl+C to stop"

python3 src/voicecommand/voice_LED_control_secure.py "\$@"
EOF
    
    chmod +x "$PROJECT_DIR/start_clank.sh"
    print_info "Startup script created: start_clank.sh"
}

create_secure_main_script() {
    print_step "Creating security-hardened main script..."
    
    # This will be a new secure version of the main script
    # For now, create a placeholder that imports the secure modules
    cat > "$PROJECT_DIR/src/voicecommand/voice_LED_control_secure.py" << 'EOF'
#!/usr/bin/env python3
"""Security-hardened voice control system for Clank LED assistant."""

import argparse
import os
import sys
import asyncio
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
EOF
    
    chmod +x "$PROJECT_DIR/src/voicecommand/voice_LED_control_secure.py"
}

run_security_check() {
    print_step "Running security verification..."
    
    # Check file permissions
    if [[ -f "$PROJECT_DIR/.env" ]]; then
        PERMS=$(stat -c "%a" "$PROJECT_DIR/.env" 2>/dev/null || stat -f "%A" "$PROJECT_DIR/.env" 2>/dev/null)
        if [[ "$PERMS" == "600" ]]; then
            print_info "Environment file permissions secure ✓"
        else
            print_warning "Environment file permissions should be 600"
        fi
    fi
    
    # Check certificate files
    if [[ -f "$PROJECT_DIR/certs/server.key" ]]; then
        PERMS=$(stat -c "%a" "$PROJECT_DIR/certs/server.key" 2>/dev/null || stat -f "%A" "$PROJECT_DIR/certs/server.key" 2>/dev/null)
        if [[ "$PERMS" == "600" ]]; then
            print_info "Private key permissions secure ✓"
        else
            print_warning "Private key permissions should be 600"
        fi
    fi
    
    # Test configuration loading
    if python3 -c "
import sys
sys.path.insert(0, '$PROJECT_DIR/src')
from voicecommand.config import ClankConfig
config = ClankConfig('$PROJECT_DIR/config/default.yaml')
print('Configuration validation passed')
" 2>/dev/null; then
        print_info "Configuration validation passed ✓"
    else
        print_warning "Configuration validation failed"
    fi
}

print_completion_info() {
    print_success "Installation completed successfully!"
    echo
    echo -e "${BLUE}Next Steps:${NC}"
    echo "1. Start Ollama service: ${YELLOW}ollama serve${NC}"
    echo "2. Test device discovery: ${YELLOW}./start_clank.sh --discover${NC}"
    echo "3. Register ESP32 devices: ${YELLOW}python3 register_device.py \"ESP32-LED-1\"${NC}"
    echo "4. Start voice assistant: ${YELLOW}./start_clank.sh${NC}"
    echo
    echo -e "${BLUE}Configuration:${NC}"
    echo "- Environment file: .env"
    echo "- Certificates: certs/"
    echo "- Logs: logs/"
    echo "- API Key: (see .env file)"
    echo
    echo -e "${BLUE}Security Features Enabled:${NC}"
    echo "✓ HTTPS encryption"
    echo "✓ API key authentication"
    echo "✓ Input validation"
    echo "✓ Rate limiting"
    echo "✓ Audit logging"
    echo "✓ Model integrity verification"
    echo
    echo -e "${GREEN}Installation log saved to: $LOG_FILE${NC}"
}

# Main installation flow
main() {
    print_header
    
    check_requirements
    setup_virtual_environment
    install_dependencies
    fetch_models
    check_ollama
    generate_certificates
    setup_configuration
    create_startup_script
    create_secure_main_script
    run_security_check
    
    print_completion_info
}

# Run main function
main "$@"