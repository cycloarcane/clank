# Clank – Security-Hardened Voice‑Controlled LED Assistant

> **🔒 Enhanced Security Branch**: This is the security-hardened version of Clank with comprehensive security improvements, authentication, HTTPS encryption, and enterprise-grade safety features.

Clank transforms spoken commands into secure JSON actions for LED strips and IoT devices. This enhanced version features military-grade security with local AI models, zero-trust architecture, and comprehensive audit logging.

## 🛡️ Security Features

- **🔐 API Key Authentication**: Cryptographically secure device registration and authentication
- **🔒 HTTPS Encryption**: TLS 1.3 encrypted communications with auto-generated certificates  
- **🛡️ Input Validation**: Multi-layer sanitization preventing injection attacks
- **📊 Rate Limiting**: Configurable request throttling and resource protection
- **📋 Audit Logging**: Comprehensive security event tracking and forensics
- **🔍 Service Discovery**: Secure mDNS device discovery replacing hardcoded IPs
- **✅ Model Integrity**: SHA256 verification of all AI models and assets
- **🚫 Zero External Dependencies**: All AI processing happens locally

## 🚀 Quick Start (Automated Installation)

```bash
# Clone the security-hardened branch
git clone -b security-hardened https://github.com/your-repo/clank.git
cd clank

# Run the automated installer (handles everything!)
./install.sh

# Start the voice assistant
./start_clank.sh
```

The installer automatically:
- ✅ Verifies system requirements
- ✅ Creates Python virtual environment  
- ✅ Installs all dependencies
- ✅ Fetches and verifies AI models
- ✅ Generates HTTPS certificates
- ✅ Creates secure configuration
- ✅ Sets up authentication system
- ✅ Configures logging and monitoring

## 📋 Prerequisites

### Required Software
- **Python 3.8+** with pip
- **Ollama** (for LLM processing): [ollama.ai](https://ollama.ai)
- **Git** and **curl**

### System Dependencies
**Ubuntu/Debian:**
```bash
sudo apt-get install libsndfile1 portaudio19-dev python3-venv
```

**macOS:**
```bash
brew install portaudio
```

**Ollama Setup:**
```bash
# Install and start Ollama
ollama serve

# Pull recommended model
ollama pull qwen3:14b
```

## 🔧 Manual Installation

If you prefer manual setup:

### 1. Environment Setup
```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements-secure.txt
```

### 2. Fetch AI Models
```bash
# Download and verify models
./scripts/fetch_moonshine.sh

# Verify integrity
sha256sum -c SHA256SUMS
```

### 3. Generate Certificates
```bash
# Create HTTPS certificates
python3 scripts/generate_certs.py --hostname localhost

# Set environment variables
export CLANK_HTTPS_CERT=certs/server.crt
export CLANK_HTTPS_KEY=certs/server.key
export CLANK_ENABLE_HTTPS=true
```

### 4. Configure Security
```bash
# Generate API key
export CLANK_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Set authentication
export CLANK_REQUIRE_AUTH=true
export CLANK_LLM_MODEL=qwen3:14b
```

## 🎯 Usage

### Starting the Voice Assistant
```bash
# Basic startup
./start_clank.sh

# With custom configuration
./start_clank.sh --config config/production.yaml

# Discovery mode only
./start_clank.sh --discover
```

### Device Management
```bash
# Register a new ESP32 device
python3 register_device.py "Kitchen-LEDs"

# List registered devices
python3 -c "
from src.voicecommand.auth import AuthManager
auth = AuthManager()
for device in auth.list_devices():
    print(f'{device.name}: {device.device_id}')
"
```

### Voice Commands
- **"Computer, turn on red LED"**
- **"Computer, set blue LED to 50%"**  
- **"Computer, turn off all LEDs"**
- **"Computer, toggle green light"**

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Voice Input   │───▶│   Clank Core     │───▶│   ESP32 LEDs    │
│                 │    │                  │    │                 │
│ • Microphone    │    │ • Authentication │    │ • HTTPS Server  │
│ • VAD Detection │    │ • Input Validation│    │ • API Key Auth  │
│ • Moonshine ASR │    │ • Rate Limiting  │    │ • JSON Commands │
└─────────────────┘    │ • Audit Logging  │    │ • LED Control   │
                       │ • HTTPS Client   │    └─────────────────┘
┌─────────────────┐    │ • Service Discovery│    
│   Local LLM     │◀───│                  │    ┌─────────────────┐
│                 │    └──────────────────┘    │   Monitoring    │
│ • Ollama        │                            │                 │
│ • Intent Parse  │                            │ • Audit Logs    │
│ • JSON Output   │                            │ • Error Tracking│
└─────────────────┘                            │ • Security Events│
                                               └─────────────────┘
```

## 📁 Project Structure

```
clank/
├── 📄 README-SECURE.md          ← This enhanced security guide
├── 📄 requirements-secure.txt   ← Security-enhanced dependencies
├── 🔧 install.sh                ← One-command automated installer
├── 🚀 start_clank.sh           ← Secure startup script
├── 📊 SECURITY_PROGRESS.md     ← Implementation progress tracking
├── 
├── 📁 config/                   ← Configuration management
│   └── 🔧 default.yaml         ← Default secure configuration
├── 📁 certs/                    ← HTTPS certificates (auto-generated)
├── 📁 logs/                     ← Application and audit logs
├── 
├── 📁 scripts/
│   ├── 🔐 generate_certs.py    ← HTTPS certificate generator
│   └── 📦 fetch_moonshine.sh   ← Model fetcher with integrity check
├── 
├── 📁 src/voicecommand/
│   ├── 🎯 voice_LED_control_secure.py  ← Security-hardened main app
│   ├── ⚙️ config.py            ← Secure configuration management
│   ├── 🔐 auth.py              ← Authentication & authorization
│   ├── ✅ validation.py        ← Input validation & sanitization
│   ├── 🔍 discovery.py         ← Service discovery system
│   ├── 📊 secure_logging.py    ← Audit logging & error handling
│   └── 🛡️ onnx_model.py       ← Integrity-verified model wrapper
└── 
└── 📁 ESP32LEDs-Secure/         ← Enhanced ESP32 firmware
    └── 🔒 ESP32LEDs-Secure.ino ← HTTPS + Auth + Validation
```

## 🔒 Security Configuration

### Environment Variables
```bash
# Core Security
CLANK_API_KEY=<auto-generated-32-char-key>
CLANK_ENABLE_HTTPS=true
CLANK_REQUIRE_AUTH=true

# Certificates
CLANK_HTTPS_CERT=certs/server.crt
CLANK_HTTPS_KEY=certs/server.key

# Rate Limiting
CLANK_MAX_REQUESTS_PER_MINUTE=60
CLANK_MAX_AUDIO_PROCESSING_TIME=30

# Logging
CLANK_LOG_LEVEL=INFO
CLANK_ENABLE_AUDIT_LOGGING=true
```

### Configuration File (config/default.yaml)
```yaml
security:
  require_authentication: true
  enable_https: true
  max_requests_per_minute: 60
  enable_audit_logging: true

network:
  use_service_discovery: true
  mdns_service_name: "_clank-led._tcp.local"
  connection_timeout: 10.0

audio:
  max_speech_seconds: 15
  vad_threshold: 0.5
```

## 🔍 Monitoring & Debugging

### Log Files
- **Application Logs**: `logs/clank.log` - General application activity
- **Audit Logs**: `logs/audit.log` - Security events and authentication
- **Install Logs**: `install.log` - Installation process details

### Security Events Tracked
- ✅ Authentication successes/failures
- 🚫 Rate limit violations  
- ⚠️ Input validation errors
- 🔍 Device discovery events
- 📝 Command processing
- 🔐 Certificate errors

### Monitoring Commands
```bash
# Watch real-time logs
tail -f logs/clank.log

# Monitor security events
tail -f logs/audit.log | jq '.'

# Check authentication status
python3 -c "
from src.voicecommand.auth import AuthManager
auth = AuthManager()
devices = auth.list_devices()
print(f'Active devices: {len([d for d in devices if d.is_active])}')
"
```

## 🛠️ ESP32 Security Setup

### Enhanced Firmware Features
- **HTTPS Server** with TLS encryption
- **API Key Authentication** for all requests
- **JSON Schema Validation** for commands
- **mDNS Service Advertisement** for discovery
- **Rate Limiting** and request validation

### Configuration
```cpp
// WiFi credentials (store securely)
const char* ssid = "your_wifi_network";
const char* password = "your_wifi_password";

// Security configuration
const char* API_KEY = "your_clank_api_key";  // From register_device.py
const bool ENABLE_HTTPS = true;
const char* MDNS_NAME = "clank-led-kitchen";
```

## 🔧 Troubleshooting

### Common Issues

**❌ "Authentication failed"**
```bash
# Regenerate API key
export CLANK_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Re-register ESP32 device
python3 register_device.py "ESP32-Device"
```

**❌ "Certificate verification failed"**
```bash
# Regenerate certificates
python3 scripts/generate_certs.py --hostname localhost

# Check certificate validity
openssl x509 -in certs/server.crt -text -noout
```

**❌ "No devices discovered"**
```bash
# Check network connectivity
./start_clank.sh --discover

# Verify ESP32 is advertising mDNS
avahi-browse -r _clank-led._tcp  # Linux
dns-sd -B _clank-led._tcp        # macOS
```

**❌ "Rate limit exceeded"**
```bash
# Check current limits
grep "rate_limit" logs/audit.log

# Adjust limits in config
export CLANK_MAX_REQUESTS_PER_MINUTE=120
```

## 🔒 Security Best Practices

### For Production Deployment

1. **🔄 Regular Key Rotation**
   ```bash
   # Monthly API key rotation
   ./scripts/rotate_api_keys.sh
   ```

2. **📊 Log Monitoring**
   ```bash
   # Set up log monitoring
   grep "SECURITY" logs/audit.log | tail -100
   ```

3. **🔍 Vulnerability Scanning**
   ```bash
   # Scan dependencies
   pip-audit
   
   # Update dependencies
   pip install --upgrade -r requirements-secure.txt
   ```

4. **🌐 Network Isolation**
   - Run Clank on isolated VLAN
   - Use firewall rules for device access
   - Monitor network traffic patterns

## 📞 Support & Contribution

### Getting Help
- 📖 **Documentation**: See inline code documentation
- 🐛 **Issues**: Open GitHub issue with logs
- 💬 **Discussions**: Security questions welcome

### Security Reporting
- 🔒 **Security Issues**: Email security@yourproject.com
- 📋 **Audit Results**: Include in security reports
- 🔍 **Vulnerability Disclosure**: Follow responsible disclosure

## 📄 License

MIT License with additional security considerations (see `LICENSE` file)

---

## 🆚 Comparison: Original vs Security-Hardened

| Feature | Original Clank | Security-Hardened |
|---------|---------------|-------------------|
| **Authentication** | ❌ None | ✅ API Key + Device Registration |
| **Encryption** | ❌ Plain HTTP | ✅ HTTPS/TLS 1.3 |
| **Input Validation** | ❌ Basic | ✅ Multi-layer + Sanitization |
| **Rate Limiting** | ❌ None | ✅ Configurable Throttling |
| **Audit Logging** | ❌ Basic logs | ✅ Security Event Tracking |
| **Service Discovery** | ❌ Hardcoded IPs | ✅ Secure mDNS |
| **Error Handling** | ❌ Verbose errors | ✅ Sanitized Error Messages |
| **Installation** | ❌ Manual steps | ✅ One-command automated |
| **Monitoring** | ❌ Limited | ✅ Comprehensive metrics |
| **Model Security** | ✅ SHA256 verified | ✅ Enhanced verification |

**🚀 Ready to secure your voice-controlled LED system? Run `./install.sh` and get started in minutes!**