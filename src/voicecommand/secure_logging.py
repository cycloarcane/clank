"""Secure logging and error handling for Clank."""

import logging
import logging.handlers
import os
import json
import time
import threading
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import traceback

class LogLevel(Enum):
    """Log levels for security events."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    SECURITY = "SECURITY"

class SecurityEventType(Enum):
    """Types of security events to log."""
    AUTHENTICATION_SUCCESS = "auth_success"
    AUTHENTICATION_FAILURE = "auth_failure"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    VALIDATION_ERROR = "validation_error"
    MALICIOUS_INPUT = "malicious_input"
    DEVICE_DISCOVERY = "device_discovery"
    COMMAND_PROCESSED = "command_processed"
    CONFIGURATION_CHANGE = "config_change"
    CERTIFICATE_ERROR = "cert_error"
    NETWORK_ERROR = "network_error"

@dataclass
class SecurityEvent:
    """Security event for audit logging."""
    timestamp: float
    event_type: SecurityEventType
    severity: LogLevel
    source_ip: str
    user_agent: Optional[str]
    device_id: Optional[str]
    message: str
    details: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data['event_type'] = self.event_type.value
        data['severity'] = self.severity.value
        return data

class SecureFormatter(logging.Formatter):
    """Custom formatter that sanitizes log messages."""
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Patterns to redact from logs
        self.redaction_patterns = [
            (r'api_key["\s]*[:=]["\s]*([A-Za-z0-9\-_]{16,})', 'api_key="[REDACTED]"'),
            (r'password["\s]*[:=]["\s]*([^\s"]+)', 'password="[REDACTED]"'),
            (r'token["\s]*[:=]["\s]*([A-Za-z0-9\-_]{16,})', 'token="[REDACTED]"'),
            (r'Authorization:\s*Bearer\s+([A-Za-z0-9\-_]+)', 'Authorization: Bearer [REDACTED]'),
            (r'([0-9]{1,3}\.){3}[0-9]{1,3}', '[IP_REDACTED]'),  # IP addresses
        ]
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with sensitive data redaction."""
        # Format the basic message
        formatted = super().format(record)
        
        # Apply redaction patterns
        import re
        for pattern, replacement in self.redaction_patterns:
            formatted = re.sub(pattern, replacement, formatted, flags=re.IGNORECASE)
        
        return formatted

class AuditLogger:
    """Specialized logger for security audit events."""
    
    def __init__(self, audit_file: str, max_size_mb: int = 10, backup_count: int = 5):
        self.audit_file = audit_file
        self.logger = logging.getLogger('clank_audit')
        self.logger.setLevel(logging.INFO)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(audit_file), exist_ok=True)
        
        # Create rotating file handler
        handler = logging.handlers.RotatingFileHandler(
            audit_file,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count
        )
        
        # Use JSON formatter for audit logs
        handler.setFormatter(JsonFormatter())
        self.logger.addHandler(handler)
        
        # Thread-safe event buffer
        self._event_buffer: List[SecurityEvent] = []
        self._buffer_lock = threading.Lock()
        self._flush_interval = 5.0  # seconds
        self._flush_thread = None
        self._stop_flushing = False
        
        self._start_flush_thread()
    
    def _start_flush_thread(self):
        """Start background thread to flush events."""
        self._stop_flushing = False
        self._flush_thread = threading.Thread(target=self._flush_events_periodically, daemon=True)
        self._flush_thread.start()
    
    def _flush_events_periodically(self):
        """Periodically flush buffered events."""
        while not self._stop_flushing:
            try:
                time.sleep(self._flush_interval)
                self.flush_events()
            except Exception as e:
                # Use basic logging to avoid recursion
                print(f"Error in audit log flush thread: {e}")
    
    def log_security_event(self, 
                          event_type: SecurityEventType,
                          message: str,
                          severity: LogLevel = LogLevel.INFO,
                          source_ip: str = "unknown",
                          user_agent: Optional[str] = None,
                          device_id: Optional[str] = None,
                          details: Optional[Dict[str, Any]] = None):
        """Log a security event."""
        
        event = SecurityEvent(
            timestamp=time.time(),
            event_type=event_type,
            severity=severity,
            source_ip=source_ip,
            user_agent=user_agent,
            device_id=device_id,
            message=message,
            details=details or {}
        )
        
        with self._buffer_lock:
            self._event_buffer.append(event)
            
            # Flush immediately for critical events
            if severity in [LogLevel.ERROR, LogLevel.CRITICAL]:
                self._flush_events_now()
    
    def _flush_events_now(self):
        """Flush all buffered events immediately."""
        events_to_flush = []
        with self._buffer_lock:
            events_to_flush = self._event_buffer.copy()
            self._event_buffer.clear()
        
        for event in events_to_flush:
            try:
                self.logger.info(json.dumps(event.to_dict()))
            except Exception as e:
                # Fallback to basic logging
                print(f"Error writing audit log: {e}")
    
    def flush_events(self):
        """Flush buffered events."""
        self._flush_events_now()
    
    def stop(self):
        """Stop the audit logger and flush remaining events."""
        self._stop_flushing = True
        if self._flush_thread:
            self._flush_thread.join(timeout=1.0)
        self.flush_events()

class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logs."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format record as JSON."""
        try:
            # Parse the message as JSON if it's already JSON
            message_data = json.loads(record.getMessage())
        except (json.JSONDecodeError, ValueError):
            # If not JSON, create a simple structure
            message_data = {
                'timestamp': time.time(),
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage()
            }
            
            # Add exception info if present
            if record.exc_info:
                message_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(message_data, default=str)

class SecureErrorHandler:
    """Handles errors securely without exposing sensitive information."""
    
    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self.audit_logger = audit_logger
        self.logger = logging.getLogger(__name__)
    
    def handle_validation_error(self, error: Exception, context: str = "") -> str:
        """Handle validation errors securely."""
        error_id = self._generate_error_id(error)
        safe_message = "Input validation failed"
        
        # Log detailed error for debugging
        self.logger.error(f"Validation error {error_id}: {str(error)} | Context: {context}")
        
        # Log security event
        if self.audit_logger:
            self.audit_logger.log_security_event(
                SecurityEventType.VALIDATION_ERROR,
                f"Validation error {error_id}",
                LogLevel.WARNING,
                details={'error_id': error_id, 'context': context}
            )
        
        return f"{safe_message} (Error ID: {error_id})"
    
    def handle_authentication_error(self, error: Exception, source_ip: str = "unknown") -> str:
        """Handle authentication errors securely."""
        error_id = self._generate_error_id(error)
        safe_message = "Authentication failed"
        
        # Log detailed error
        self.logger.warning(f"Authentication error {error_id}: {str(error)} | IP: {source_ip}")
        
        # Log security event
        if self.audit_logger:
            self.audit_logger.log_security_event(
                SecurityEventType.AUTHENTICATION_FAILURE,
                f"Authentication failed {error_id}",
                LogLevel.WARNING,
                source_ip=source_ip,
                details={'error_id': error_id}
            )
        
        return f"{safe_message} (Error ID: {error_id})"
    
    def handle_network_error(self, error: Exception, endpoint: str = "") -> str:
        """Handle network errors securely."""
        error_id = self._generate_error_id(error)
        safe_message = "Network communication failed"
        
        # Log error
        self.logger.error(f"Network error {error_id}: {str(error)} | Endpoint: {endpoint}")
        
        # Log security event
        if self.audit_logger:
            self.audit_logger.log_security_event(
                SecurityEventType.NETWORK_ERROR,
                f"Network error {error_id}",
                LogLevel.ERROR,
                details={'error_id': error_id, 'endpoint': endpoint}
            )
        
        return f"{safe_message} (Error ID: {error_id})"
    
    def handle_unexpected_error(self, error: Exception, context: str = "") -> str:
        """Handle unexpected errors securely."""
        error_id = self._generate_error_id(error)
        safe_message = "An unexpected error occurred"
        
        # Log full traceback for debugging
        self.logger.error(f"Unexpected error {error_id}: {str(error)} | Context: {context}")
        self.logger.debug(f"Traceback for {error_id}:", exc_info=True)
        
        return f"{safe_message} (Error ID: {error_id})"
    
    def _generate_error_id(self, error: Exception) -> str:
        """Generate a unique error ID for tracking."""
        error_str = f"{type(error).__name__}:{str(error)}:{time.time()}"
        return hashlib.sha256(error_str.encode()).hexdigest()[:12]

def setup_secure_logging(config) -> tuple[logging.Logger, AuditLogger, SecureErrorHandler]:
    """Set up secure logging for the application."""
    
    # Ensure log directories exist
    os.makedirs(os.path.dirname(config.logging.file), exist_ok=True)
    os.makedirs(os.path.dirname(config.logging.audit_file), exist_ok=True)
    
    # Configure main logger
    logger = logging.getLogger('clank')
    logger.setLevel(getattr(logging, config.logging.level.upper()))
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Create rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        config.logging.file,
        maxBytes=config.logging.max_size_mb * 1024 * 1024,
        backupCount=config.logging.backup_count
    )
    file_handler.setFormatter(SecureFormatter())
    logger.addHandler(file_handler)
    
    # Create console handler with secure formatting
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(SecureFormatter())
    logger.addHandler(console_handler)
    
    # Create audit logger
    audit_logger = AuditLogger(
        config.logging.audit_file,
        config.logging.max_size_mb,
        config.logging.backup_count
    )
    
    # Create error handler
    error_handler = SecureErrorHandler(audit_logger)
    
    return logger, audit_logger, error_handler