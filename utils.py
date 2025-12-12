# utils.py
"""
FILE: utils.py
DESCRIPTION:
  Shared helper functions used across the project.
  - clean_mac(): Sanitizes device IDs for MQTT topics.
  - calculate_dew_point(): Math formula to calculate Dew Point from Temp/Humidity.
  - get_system_mac(): Generates a unique ID for the bridge itself based on hardware.
"""
import re
import math
import socket
import config

# Global cache
_SYSTEM_MAC = None

def get_system_mac():
    global _SYSTEM_MAC
    if _SYSTEM_MAC: 
        return _SYSTEM_MAC

    # 1. PREFERRED: Use Static ID from Config
    if config.BRIDGE_ID:
        _SYSTEM_MAC = config.BRIDGE_ID
        return _SYSTEM_MAC
    
    try:
        # 2. FALLBACK: Use Hostname (Dynamic on HAOS!)
        host_id = socket.gethostname()
        
        if not host_id:
            host_id = "rtl-bridge-default"
            
        _SYSTEM_MAC = host_id
        return _SYSTEM_MAC

    except Exception:
        return "rtl-bridge-error-id"

def clean_mac(mac):
    """Cleans up MAC/ID string for use in topic/unique IDs."""
    # Removes special characters to make it MQTT-safe
    cleaned = re.sub(r'[^A-Za-z0-9]', '', str(mac))
    return cleaned.lower() if cleaned else "unknown"

def calculate_dew_point(temp_c, humidity):
    """Calculates Dew Point (F) using Magnus Formula."""
    if temp_c is None or humidity is None:
        return None
    if humidity <= 0:
        return None 
    try:
        b = 17.62
        c = 243.12
        gamma = (b * temp_c / (c + temp_c)) + math.log(humidity / 100.0)
        dp_c = (c * gamma) / (b - gamma)
        return round(dp_c * 1.8 + 32, 1) # Return Fahrenheit
    except Exception:
        return None