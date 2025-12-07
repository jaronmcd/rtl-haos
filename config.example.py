# config.py

"""
FILE: config.py
DESCRIPTION:
  Master configuration file for the RTL-433 to MQTT Bridge.
  
  HOW TO USE:
  1. Rename this file from 'config.example.py' to 'config.py'.
  2. Edit the settings below to match your network and hardware.
  3. Restart the service for changes to take effect.
"""

# ==============================================================================
# CONNECTION: MQTT BROKER
# ==============================================================================
# Enter the credentials for your MQTT Broker (usually running on Home Assistant).
MQTT_SETTINGS = {
    "host": "192.168.1.123",  # IP address of your broker
    "port": 1883,             # Standard MQTT port (8883 for SSL)
    "user": "mqtt_user",      # Username (defined in HA -> People or Mosquito Add-on)
    "pass": "mqtt_password",  # Password
    "keepalive": 60,          # How often to send a "heartbeat" to stay connected
}

# ==============================================================================
# HARDWARE: RTL-SDR RADIO CONFIGURATION
# ==============================================================================

# SINGLE RADIO SETUP:
# If you only have one USB RTL-SDR dongle plugged in, leave this list EMPTY.
# The script will automatically find the first available radio.
RTL_CONFIG = []

# ==============================================================================
# MULTI-RADIO & FREQUENCY HOPPING SETUP:
# ==============================================================================
# You can define multiple SDRs, or a single SDR that "hops" between frequencies.

# HOPPING EXAMPLE:
# To monitor both 433MHz and 915MHz with a single dongle (switching every 60s):
# RTL_CONFIG = [
#     {
#         "name": "Hopping Radio",
#         "freq": ["433.92M", "915M"], 
#         "hop_interval": 60, # Switch frequency every 60 seconds
#         "rate": "1024k"     # Compromise sample rate
#     }
# ]

# MULTI-DONGLE EXAMPLE:
# When using multiple radios, EVERY radio must have a unique 'id'.
# RTL_CONFIG = [
#     # Radio 1: Listens for Weather Stations (Acurite, Ambient Weather)
#     {
#         "name": "Weather Radio", 
#         "id": "101",          # The Serial Number (set via rtl_eeprom)
#         "freq": "433.92M",    # Standard frequency for most weather sensors
#         "rate": "250k"        # Lower sample rate reduces CPU usage
#     },
#     },
#     # Radio 2: Listens for Utility Meters (Gas/Water/Electric)
#     {
#         "name": "Utility Radio", 
#         "id": "102",          # The Serial Number (set via rtl_eeprom)
#         "freq": "912.6M",     # Standard US frequency for ERT meters
#         "rate": "2400k"       # Higher rate often needed for hopping signals
#     },
# ]

# POWER USER EXAMPLE:
# RTL_CONFIG = [
#     {
#         "name": "Custom Radio",
#         "freq": "433.92M",
#         # Use the special version I compiled
#         "rtl_433_cmd": "/opt/rtl_433_custom/build/src/rtl_433",
#         # Set Gain to 28dB, PPM error to 12
#         "raw_params": "-g 28 -p 12" 
#     }
# ]

# ==============================================================================
# RTL_THROTTLE_INTERVAL
# ==============================================================================
# Some sensors transmit every 4 seconds. This spams Home Assistant's database.
# This setting buffers data for X seconds and sends the AVERAGE value.
# - 0  : Real-time. Every packet is sent immediately.
# - 30 : Buffer for 30 seconds, then send the average (Recommended).
# - 60 : Buffer for 1 minute.
RTL_THROTTLE_INTERVAL = 30

# ==============================================================================
# ENTITY LIFECYCLE: EXPIRATION (UNAVAILABLE)
# ==============================================================================

# RTL_EXPIRE_AFTER:
# How many seconds of silence before Home Assistant marks the entity as "Unavailable" (Greyed out).
# - It does NOT delete the entity.
# - It simply indicates the device might be offline or out of battery.
# - 600 seconds = 10 minutes.
RTL_EXPIRE_AFTER = 600

# ==============================================================================
# ENTITY LIFECYCLE: AUTO-REMOVAL (DELETION)
# ==============================================================================

# DEVICE_PURGE_INTERVAL:
# How many seconds of silence before we forcefully DELETE the device from Home Assistant.
# 
# VALUE GUIDE:
# - 0       : Disabled. Devices stay forever (even if you sell the sensor).
# - 3600    : 1 Hour. Good for tracking temporary signals.
# - 86400   : 24 Hours. Recommended. Removes passing cars/neighbors after a day.
#
# NOTE: If the device transmits again later, it will be re-created instantly, 
# but gaps in history may occur.
DEVICE_PURGE_INTERVAL = 86400

# ==============================================================================
# DATA FILTERING: IGNORING DATA
# ==============================================================================

# SKIP_KEYS:
# These are fields inside the JSON data that we simply don't care about.
# Removing them here saves network bandwidth and database space in Home Assistant.
SKIP_KEYS = [
    "time",      # HA adds its own timestamp
    "protocol",  # The specific protocol ID (usually irrelevant for dashboards)
    "mod",       # Modulation type (ASK/FSK - technical radio data)
    "id",        # We use the ID in the topic, we don't need it as a separate sensor value
    "mic",       # Integrity check (CRC) - if it failed, we wouldn't see the data anyway
]

# ==============================================================================
# DEVICE FILTERING: WHITELIST & BLACKLIST
# ==============================================================================
# Use these lists to control which devices appear in Home Assistant.
# Supports wildcards (*) to match patterns.

# BLACKLIST (Block specific annoyances):
# Devices listed here will be ignored.
# Useful for blocking:
# - Tire Pressure (TPMS) sensors from cars driving by.
# - Your neighbor's alarm system.
DEVICE_BLACKLIST = [
    "SimpliSafe*",  # Block all SimpliSafe security sensors
    "EezTire*",     # Block EezTire TPMS sensors
    "Schrader*",    # Block Schrader TPMS sensors
    "Generic-Remote*", # Block generic car keyfobs
]

# WHITELIST (Strict Mode):
# If you populate this list, the Blacklist is IGNORED.
# ONLY devices matching these patterns will be allowed.
# Leave this empty [] to use the Blacklist instead.
DEVICE_WHITELIST = []  
# Example: Only allow my specific weather station and freezer thermometer:
# DEVICE_WHITELIST = ["Acurite-5n1*", "Acurite-986*"]


# ==============================================================================
# HOME ASSISTANT: ENTITY CATEGORIZATION
# ==============================================================================

# MAIN_SENSORS:
# In Home Assistant, entities can be "Controls", "Sensors", or "Diagnostics".
# "Diagnostics" are usually hidden in a separate tab on the device page.
# Any sensor name listed below is treated as a PRIMARY sensor (shown prominently).
# Anything NOT listed here will be categorized as "Diagnostic".
MAIN_SENSORS = [
    # System Status
    "sys_device_count",
    
    # Environmental
    "temperature", "temperature_C", "temperature_F", "dew_point",
    "humidity", 
    "pressure_hpa", "pressure_inhg", "pressure_PSI",
    "co2", "mics_ratio", "mq2_ratio", 
    
    # Magnetometer / Earth Field
    "mag_uT", "geomag_index",
    
    # Wind
    "wind_avg_km_h", "wind_avg_mi_h", 
    "wind_gust_km_h", "wind_gust_mi_h",
    "wind_dir_deg", "wind_dir",
    
    # Precipitation
    "rain_mm", "rain_in", 
    "rain_rate_mm_h", "rain_rate_in_h",
    
    # Light / Storms
    "lux", "uv", 
    "strikes", "strike_distance", "storm_dist",
    
    # Utility Metering
    "Consumption", "consumption", "meter_reading",
]

# ==============================================================================
# ADVANCED: SYSTEM IDENTIFIERS
# ==============================================================================

# ID_SUFFIX / FORCE_NEW_IDS:
# If you change the structure of your sensors and Home Assistant gets confused,
# you can set FORCE_NEW_IDS = True.
# This appends "_v2" to every single sensor, effectively creating a brand new
# set of devices in Home Assistant and abandoning the old ones.
# KEEP THIS FALSE unless you are debugging a corrupted database.
FORCE_NEW_IDS = False
ID_SUFFIX = "_v2" if FORCE_NEW_IDS else ""


# ==============================================================================
# DEBUGGING & PERFORMANCE
# ==============================================================================

# DEBUG_RAW_JSON:
# If True, prints every single JSON line received from rtl_433 to the console.
# Useful for finding the exact model name of a device to whitelist/blacklist it.
DEBUG_RAW_JSON = False

# ==============================================================================
# TCP INPUT: REMOTE RTL_433 INSTANCES
# ==============================================================================
# Allow other machines running 'rtl_433 -F json:HOST:PORT' to send data here.
TCP_LISTEN_ENABLED = False
TCP_LISTEN_PORT = 4000