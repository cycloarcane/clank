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
OLLAMA_MODEL="qwen3:4b"
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

        configure_ollama_keepalive
    else
        print_warning "Ollama not found. Please install from https://ollama.ai"
        print_info "After installing Ollama, run: ollama pull $OLLAMA_MODEL"
    fi
}

configure_ollama_keepalive() {
    # By default Ollama evicts the model from (V)RAM after ~5 min idle, so the
    # first command after a pause pays a slow cold reload. On a dedicated Clank
    # box you usually want it resident for instant responses — this just holds
    # VRAM while idle (no compute, no GPU wear).
    if ! command -v systemctl &> /dev/null || \
       ! systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
        print_info "Ollama isn't a systemd service here — to keep the model warm,"
        print_info "start it with OLLAMA_KEEP_ALIVE=-1 in its environment."
        return 0
    fi

    echo
    print_info "Ollama unloads the model after ~5 min idle (slow first command)."
    print_info "Keeping it loaded gives instant responses (holds VRAM; no GPU wear)."
    read -p "Keep the LLM loaded in VRAM permanently (OLLAMA_KEEP_ALIVE=-1)? (Y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        print_info "Leaving Ollama's default unload behaviour (set later by re-running)."
        return 0
    fi

    local dropin="/etc/systemd/system/ollama.service.d/keepalive.conf"
    print_info "Writing $dropin (needs sudo)..."
    sudo mkdir -p "$(dirname "$dropin")"
    sudo tee "$dropin" > /dev/null <<'DROPIN'
[Service]
Environment="OLLAMA_KEEP_ALIVE=-1"
DROPIN
    sudo systemctl daemon-reload
    sudo systemctl restart ollama
    print_info "Ollama will keep models resident. Verify with: ollama ps (UNTIL = Forever)."
}

setup_configuration() {
    print_step "Setting up configuration..."

    mkdir -p "$PROJECT_DIR/logs"
    mkdir -p "$PROJECT_DIR/config"

    # Broker credentials live in ESP32LEDs/secrets.h (the single source shared by
    # the broker setup script and Clank). Seed it from the template if missing.
    SECRETS="$PROJECT_DIR/ESP32LEDs/secrets.h"
    if [[ ! -f "$SECRETS" ]]; then
        cp "$PROJECT_DIR/ESP32LEDs/secrets.h.example" "$SECRETS"
        print_info "Created ESP32LEDs/secrets.h from the template."
    fi

    MQTT_USER=$(grep -oP '#define MQTT_USER\s+"\K[^"]+' "$SECRETS" 2>/dev/null || echo "clank")
    MQTT_PASS=$(grep -oP '#define MQTT_PASS\s+"\K[^"]+' "$SECRETS" 2>/dev/null || echo "")

    # Block on a missing password — an empty MQTT_PASS means the broker will
    # reject every connection. Offer to generate one and write it into secrets.h.
    if [[ -z "$MQTT_PASS" ]]; then
        echo
        print_warning "MQTT_PASS is not set in ESP32LEDs/secrets.h."
        print_info "A strong password is required — the broker refuses anonymous connections."
        echo
        read -p "Generate a random password automatically? (Y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            MQTT_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
            sed -i "s|#define MQTT_PASS\s*\"[^\"]*\"|#define MQTT_PASS     \"$MQTT_PASS\"|" "$SECRETS"
            print_info "Password written to ESP32LEDs/secrets.h: $MQTT_PASS"
            print_warning "Copy this password into WLED (Config → Sync Interfaces → MQTT)"
            print_warning "and each smart plug's MQTT config, then re-flash or reconfigure them."
        else
            echo
            print_error "Set MQTT_PASS in ESP32LEDs/secrets.h, then re-run the installer."
            exit 1
        fi
    fi

    # Create or update the runtime env file. If one already exists (e.g. copied
    # from another machine), only update the lines we own so hand-edited values
    # like ESP32_IP or ESP32_API_KEY are preserved.
    ENV_FILE="$PROJECT_DIR/.env"
    if [[ -f "$ENV_FILE" ]]; then
        sed -i "s|^MQTT_USER=.*|MQTT_USER=\"$MQTT_USER\"|" "$ENV_FILE"
        sed -i "s|^MQTT_PASS=.*|MQTT_PASS=\"$MQTT_PASS\"|" "$ENV_FILE"
        sed -i "s|^CLANK_LLM_MODEL=.*|CLANK_LLM_MODEL=$OLLAMA_MODEL|" "$ENV_FILE"
        print_info "Updated existing $ENV_FILE"
    else
        cat > "$ENV_FILE" << EOF
# Clank runtime config — generated by installer on $(date)
# Contains a secret (MQTT password). Never commit it (already in .gitignore).

# MQTT broker credentials — must match the mosquitto passwd entry and secrets.h.
MQTT_USER="$MQTT_USER"
MQTT_PASS="$MQTT_PASS"

# LLM (local Ollama)
CLANK_LLM_MODEL=$OLLAMA_MODEL
CLANK_LLM_ENDPOINT=http://127.0.0.1:11434/api/generate

# Logging
CLANK_LOG_LEVEL=INFO
EOF
        print_info "Configuration file created: $ENV_FILE"
    fi

    chmod 600 "$ENV_FILE"
}

setup_broker() {
    print_step "Setting up mosquitto MQTT broker..."

    if ! command -v mosquitto >/dev/null 2>&1; then
        print_info "mosquitto not found — installing..."
        if command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --needed --noconfirm mosquitto
        elif command -v apt-get >/dev/null 2>&1; then
            sudo apt-get install -y mosquitto mosquitto-clients
        else
            print_warning "Unknown package manager — install mosquitto manually, then re-run."
            return 0
        fi
    fi

    echo
    print_info "Running scripts/setup_mosquitto.sh (needs sudo) ..."
    sudo bash "$PROJECT_DIR/scripts/setup_mosquitto.sh"
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
    echo "1. Flash the strip with WLED (install.wled.me) and set its MQTT creds"
    echo "   (from ${YELLOW}ESP32LEDs/secrets.h${NC}) via Config → Sync Interfaces → MQTT."
    echo "   Register your devices in ${YELLOW}config/devices.yaml${NC}."
    echo "2. Start Ollama: ${YELLOW}ollama serve${NC}  (model: $OLLAMA_MODEL)"
    echo "3. Start Clank: ${YELLOW}./start_clank.sh${NC}  (say \"hey clank ...\")"
    echo
    echo -e "${BLUE}Configuration:${NC}"
    echo "- Runtime env:   .env                 (MQTT password, LLM, log level)"
    echo "- Devices:       config/devices.yaml  (strips + plugs by spoken name)"
    echo "- Settings:      config/default.yaml"
    echo "- Logs:          logs/"
    echo
    echo -e "${BLUE}Features:${NC}"
    echo "✓ Local wake word (\"hey clank\"), STT, and LLM — fully offline"
    echo "✓ Input + LLM-output validation; unknown/misheard targets rejected"
    echo "✓ MQTT auth (broker requires username/password)"
    echo "✓ Wake-model + STT-model integrity verification (SHA256-pinned)"
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
    setup_configuration
    setup_broker
    run_security_check
    
    print_completion_info
}

# Run main function
main "$@"