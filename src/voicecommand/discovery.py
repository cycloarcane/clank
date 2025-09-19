"""Service discovery for automatic ESP32 device detection."""

import socket
import time
import logging
import json
import threading
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass
from zeroconf import ServiceBrowser, Zeroconf, ServiceListener, ServiceInfo
import requests

@dataclass
class DiscoveredDevice:
    """Represents a discovered ESP32 device."""
    name: str
    address: str
    port: int
    protocol: str  # 'http' or 'https'
    properties: Dict[str, str]
    last_seen: float
    
    @property
    def endpoint(self) -> str:
        """Get the full endpoint URL."""
        return f"{self.protocol}://{self.address}:{self.port}"
    
    @property
    def led_control_url(self) -> str:
        """Get the LED control endpoint URL."""
        return f"{self.endpoint}/led-control"

class DeviceDiscoveryListener(ServiceListener):
    """Listens for Clank LED device announcements."""
    
    def __init__(self, callback: Callable[[DiscoveredDevice], None]):
        self.callback = callback
        self.logger = logging.getLogger(__name__)
    
    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is updated."""
        self.add_service(zc, type_, name)
    
    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is removed."""
        self.logger.info(f"Device removed: {name}")
    
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a new service is discovered."""
        info = zc.get_service_info(type_, name)
        if info:
            try:
                # Parse device information
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port
                
                # Get properties
                properties = {}
                if info.properties:
                    for key, value in info.properties.items():
                        properties[key.decode('utf-8')] = value.decode('utf-8')
                
                # Determine protocol
                protocol = 'https' if properties.get('secure') == 'true' else 'http'
                
                device = DiscoveredDevice(
                    name=name,
                    address=address,
                    port=port,
                    protocol=protocol,
                    properties=properties,
                    last_seen=time.time()
                )
                
                self.logger.info(f"Discovered device: {device.name} at {device.endpoint}")
                self.callback(device)
                
            except Exception as e:
                self.logger.error(f"Error processing discovered service {name}: {e}")

class DeviceDiscovery:
    """Manages automatic discovery of ESP32 LED devices."""
    
    def __init__(self, service_type: str = "_clank-led._tcp.local."):
        self.service_type = service_type
        self.devices: Dict[str, DiscoveredDevice] = {}
        self.logger = logging.getLogger(__name__)
        self.zeroconf = None
        self.browser = None
        self.discovery_timeout = 5.0
        self.cleanup_interval = 60.0  # seconds
        self.device_timeout = 300.0   # 5 minutes
        self._cleanup_thread = None
        self._stop_cleanup = False
        
    def start_discovery(self) -> None:
        """Start the service discovery process."""
        try:
            self.zeroconf = Zeroconf()
            listener = DeviceDiscoveryListener(self._on_device_discovered)
            self.browser = ServiceBrowser(self.zeroconf, self.service_type, listener)
            
            # Start cleanup thread
            self._stop_cleanup = False
            self._cleanup_thread = threading.Thread(target=self._cleanup_old_devices, daemon=True)
            self._cleanup_thread.start()
            
            self.logger.info(f"Started device discovery for {self.service_type}")
            
        except Exception as e:
            self.logger.error(f"Failed to start device discovery: {e}")
            self.stop_discovery()
    
    def stop_discovery(self) -> None:
        """Stop the service discovery process."""
        self._stop_cleanup = True
        
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=1.0)
        
        if self.browser:
            self.browser.cancel()
            self.browser = None
        
        if self.zeroconf:
            self.zeroconf.close()
            self.zeroconf = None
        
        self.logger.info("Stopped device discovery")
    
    def _on_device_discovered(self, device: DiscoveredDevice) -> None:
        """Handle newly discovered device."""
        # Verify the device responds to health check
        if self._verify_device(device):
            self.devices[device.name] = device
            self.logger.info(f"Verified and added device: {device.name}")
        else:
            self.logger.warning(f"Device verification failed: {device.name}")
    
    def _verify_device(self, device: DiscoveredDevice) -> bool:
        """Verify that a discovered device is a valid Clank LED controller."""
        try:
            # Try to connect to the device health endpoint
            health_url = f"{device.endpoint}/health"
            response = requests.get(
                health_url,
                timeout=self.discovery_timeout,
                verify=False  # Allow self-signed certificates
            )
            
            if response.status_code == 200:
                # Check if response indicates it's a Clank device
                try:
                    data = response.json()
                    if data.get('service') == 'clank-led':
                        return True
                except json.JSONDecodeError:
                    pass
                
                # Also accept simple text responses
                if 'clank' in response.text.lower():
                    return True
            
        except requests.RequestException as e:
            self.logger.debug(f"Device verification failed for {device.name}: {e}")
        
        return False
    
    def _cleanup_old_devices(self) -> None:
        """Periodically remove devices that haven't been seen recently."""
        while not self._stop_cleanup:
            try:
                current_time = time.time()
                expired_devices = []
                
                for name, device in self.devices.items():
                    if current_time - device.last_seen > self.device_timeout:
                        expired_devices.append(name)
                
                for name in expired_devices:
                    del self.devices[name]
                    self.logger.info(f"Removed expired device: {name}")
                
                time.sleep(self.cleanup_interval)
                
            except Exception as e:
                self.logger.error(f"Error in device cleanup: {e}")
                time.sleep(self.cleanup_interval)
    
    def get_devices(self) -> List[DiscoveredDevice]:
        """Get list of currently discovered devices."""
        return list(self.devices.values())
    
    def get_device_by_name(self, name: str) -> Optional[DiscoveredDevice]:
        """Get a specific device by name."""
        return self.devices.get(name)
    
    def find_best_device(self) -> Optional[DiscoveredDevice]:
        """Find the best available device (most recently seen)."""
        if not self.devices:
            return None
        
        return max(self.devices.values(), key=lambda d: d.last_seen)
    
    def wait_for_devices(self, timeout: float = 10.0, min_devices: int = 1) -> List[DiscoveredDevice]:
        """Wait for devices to be discovered."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if len(self.devices) >= min_devices:
                break
            time.sleep(0.1)
        
        return self.get_devices()

class FallbackDiscovery:
    """Fallback discovery mechanism using IP scanning."""
    
    def __init__(self, ip_ranges: List[str] = None):
        self.ip_ranges = ip_ranges or ["192.168.1.0/24", "10.0.0.0/24"]
        self.logger = logging.getLogger(__name__)
        self.common_ports = [80, 443, 8080, 8443]
    
    def scan_for_devices(self, timeout: float = 2.0) -> List[DiscoveredDevice]:
        """Scan IP ranges for Clank LED devices."""
        devices = []
        
        for ip_range in self.ip_ranges:
            self.logger.info(f"Scanning IP range: {ip_range}")
            
            try:
                import ipaddress
                network = ipaddress.ip_network(ip_range, strict=False)
                
                for ip in network.hosts():
                    if self._stop_scan:
                        break
                    
                    for port in self.common_ports:
                        device = self._try_connect(str(ip), port, timeout)
                        if device:
                            devices.append(device)
                            break  # Found device on this IP, try next IP
                            
            except Exception as e:
                self.logger.error(f"Error scanning IP range {ip_range}: {e}")
        
        return devices
    
    def _try_connect(self, ip: str, port: int, timeout: float) -> Optional[DiscoveredDevice]:
        """Try to connect to a specific IP and port."""
        for protocol in ['http', 'https']:
            try:
                url = f"{protocol}://{ip}:{port}/health"
                response = requests.get(url, timeout=timeout, verify=False)
                
                if response.status_code == 200:
                    # Check if it's a Clank device
                    if 'clank' in response.text.lower():
                        return DiscoveredDevice(
                            name=f"clank-{ip}",
                            address=ip,
                            port=port,
                            protocol=protocol,
                            properties={'discovered_by': 'fallback'},
                            last_seen=time.time()
                        )
                        
            except requests.RequestException:
                continue
        
        return None

def create_discovery_service(config) -> DeviceDiscovery:
    """Create and configure device discovery service."""
    service_name = getattr(config.network, 'mdns_service_name', '_clank-led._tcp.local.')
    discovery = DeviceDiscovery(service_name)
    return discovery