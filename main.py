#!/usr/bin/env python3
"""
FILE: main.py
DESCRIPTION:
  The main executable script.
  - Checks dependencies.
  - Starts MQTT Handler.
  - Starts Data Processor (Throttling).
  - Starts RTL Managers (Radios).
  - Starts System Monitor.
  - UPDATED: Auto Mode now uses global defaults for Freq/Hopping.
  - UPDATED: Version entity removed (now part of Device Info).
"""
import builtins
from datetime import datetime

# --- 1. GLOBAL TIMESTAMP OVERRIDE ---
# Save the original print function so we don't cause an infinite recursion
_original_print = builtins.print

def timestamped_print(*args, **kwargs):
    """Adds a timestamp to every print() call."""
    # Format: [18:05:00] INFO:
    now = datetime.now().strftime("[%H:%M:%S]")
    
    # Mimic the bashio style (Short time + INFO tag)
    _original_print(f"{now} INFO:", *args, **kwargs)
    
# Overwrite Python's built-in print with our new version
builtins.print = timestamped_print
# ------------------------------------

import threading
import time
import sys
import importlib.util
import subprocess
import os
import socket

# --- PRE-FLIGHT DEPENDENCY CHECK ---
def check_dependencies():
    # 1. Check for the rtl_433 binary (System Dependency)
    if not subprocess.run(["which", "rtl_433"], capture_output=True).stdout:
        print("CRITICAL: 'rtl_433' binary not found. Please install it (e.g., sudo apt install rtl-433).")
        sys.exit(1)

    # 2. Check for Paho MQTT (Python Dependency)
    if importlib.util.find_spec("paho") is None:
        print("CRITICAL: Python dependency 'paho-mqtt' not found.")
        print("Please install requirements: uv sync")
        sys.exit(1)

check_dependencies()

import config
from mqtt_handler import HomeNodeMQTT
from utils import get_system_mac
from system_monitor import system_stats_loop

# New Imports from Split Files
from data_processor import DataProcessor
from rtl_manager import rtl_loop, discover_default_rtl_serial

def get_version():
    """Retrieves the version string from config.yaml."""
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.yaml")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                for line in f:
                    if line.strip().startswith("version:"):
                        ver = line.split(":", 1)[1].strip().replace('"', '').replace("'", "")
                        return f"v{ver}"
    except Exception:
        pass
    return "Unknown"

def main():
    ver = get_version()
    print(f"--- RTL-HAOS ({ver}) ---")

    # 1. START MQTT (With Version Info)
    mqtt_handler = HomeNodeMQTT(version=ver)
    mqtt_handler.start()

    # 2. START DATA PROCESSOR (Handles Buffering/Throttling)
    processor = DataProcessor(mqtt_handler)
    threading.Thread(target=processor.start_throttle_loop, daemon=True).start()

    # 3. GET SYSTEM IDENTITY
    sys_id = get_system_mac().replace(":", "").lower() 
    sys_model = config.BRIDGE_NAME
    sys_name = f"{sys_model} ({sys_id})"

    # 4. START RTL RADIO THREADS
    rtl_config = getattr(config, "RTL_CONFIG", None)

    if rtl_config:
        # Explicit radios from config.py (Advanced Mode)
        for radio in rtl_config:
            threading.Thread(
                target=rtl_loop,
                # Pass 'processor' so the radio can send data to it
                args=(radio, mqtt_handler, processor, sys_id, sys_model),
                daemon=True,
            ).start()
    else:
        # AUTO MODE: Detect single radio & Apply Defaults
        auto_serial = discover_default_rtl_serial()
        
        # Build the radio config dict
        if auto_serial:
            print(f"[STARTUP] Auto-detected RTL-SDR serial: {auto_serial}")
            auto_radio = {
                "name": f"RTL_{auto_serial}", 
                "id": auto_serial,
                "freq": config.RTL_DEFAULT_FREQ,             # <--- INJECTED
                "hop_interval": config.RTL_DEFAULT_HOP_INTERVAL # <--- INJECTED
            }
        else:
            print("[STARTUP] Using default RTL-SDR id '0'")
            auto_radio = {
                "name": "RTL_auto", 
                "id": "0",
                "freq": config.RTL_DEFAULT_FREQ,             # <--- INJECTED
                "hop_interval": config.RTL_DEFAULT_HOP_INTERVAL # <--- INJECTED
            }

        threading.Thread(
            target=rtl_loop,
            args=(auto_radio, mqtt_handler, processor, sys_id, sys_model),
            daemon=True,
        ).start()

    # 5. START SYSTEM MONITOR
    threading.Thread(
        target=system_stats_loop, 
        args=(mqtt_handler, sys_id, sys_model), 
        daemon=True
    ).start()

    # 6. MAIN LOOP
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping MQTT...")
        mqtt_handler.stop()

if __name__ == "__main__":
    main()