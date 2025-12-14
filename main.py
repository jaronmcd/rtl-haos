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
  - UPDATED: Now maps Manual Config Serial Numbers to Physical Indices to prevent driver crashes.
"""
import builtins
from datetime import datetime

# --- 1. GLOBAL TIMESTAMP OVERRIDE ---
_original_print = builtins.print

def timestamped_print(*args, **kwargs):
    """Adds a timestamp to every print() call."""
    now = datetime.now().strftime("[%H:%M:%S]")
    _original_print(f"{now} INFO:", *args, **kwargs)
    
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
    if not subprocess.run(["which", "rtl_433"], capture_output=True).stdout:
        print("CRITICAL: 'rtl_433' binary not found. Please install it.")
        sys.exit(1)

    if importlib.util.find_spec("paho") is None:
        print("CRITICAL: Python dependency 'paho-mqtt' not found.")
        sys.exit(1)

check_dependencies()

import config
from mqtt_handler import HomeNodeMQTT
from utils import get_system_mac
from system_monitor import system_stats_loop

# New Imports from Split Files
from data_processor import DataProcessor
from rtl_manager import rtl_loop, discover_rtl_devices

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

def show_logo(version):
    """Prints the ASCII logo with forced ANSI colors."""
    # Force ANSI codes using hex \x1b
    CYAN = "\x1b[1;36m"
    WHITE = "\x1b[1;37m"
    RESET = "\x1b[0m"

    logo = r"""
  ____  _____  _         _   _    _    ___  ____  
 |  _ \|_   _|| |       | | | |  / \  / _ \/ ___| 
 | |_) | | |  | |  ___  | |_| | / _ \| | | \___ \ 
 |  _ <  | |  | | |___| |  _  |/ ___ \ |_| |___) |
 |_| \_\ |_|  |_____|   |_| |_/_/   \_\___/|____/ 
    """
    
    # Use flush=True to ensure it hits the Docker logs instantly
    _original_print(f"{CYAN}{logo}{RESET}", flush=True) 
    _original_print(f"   {WHITE}>>> RTL-SDR Bridge for Home Assistant ({version}) <<<{RESET}", flush=True)
    _original_print("   --------------------------------------------------\n", flush=True)

def main():
    ver = get_version()
    show_logo(ver)
    time.sleep(3)

    # 2. START MQTT
    mqtt_handler = HomeNodeMQTT(version=ver)
    mqtt_handler.start()

    # 3. START DATA PROCESSOR
    processor = DataProcessor(mqtt_handler)
    threading.Thread(target=processor.start_throttle_loop, daemon=True).start()

    # 4. GET SYSTEM IDENTITY
    sys_id = get_system_mac().replace(":", "").lower() 
    sys_model = config.BRIDGE_NAME
    sys_name = f"{sys_model} ({sys_id})"

    # --- NEW: HARDWARE MAPPING ---
    # Always scan first to find where the serials actually live (Index 0 vs Index 1)
    print("[STARTUP] Scanning USB bus for RTL-SDR devices...")
    detected_devices = discover_rtl_devices()
    
    # Create a map: "102" -> 0, "101" -> 1
    serial_to_index = {}
    if detected_devices:
        for d in detected_devices:
            if 'id' in d and 'index' in d:
                serial_to_index[str(d['id'])] = d['index']
        print(f"[STARTUP] Hardware Map: {serial_to_index}")
    else:
        print("[STARTUP] Warning: No hardware detected during scan.")

    # 5. START RTL RADIO THREADS
    rtl_config = getattr(config, "RTL_CONFIG", None)

    if rtl_config:
        # --- MANUAL MODE (Advanced) ---
        print(f"[STARTUP] Loading {len(rtl_config)} radios from manual config.")
        
        for radio in rtl_config:
            target_id = radio.get("id") 
            if target_id: target_id = str(target_id).strip()
            
            if target_id and target_id in serial_to_index:
                idx = serial_to_index[target_id]
                radio['index'] = idx
                r_name = radio.get("name", "Unknown")
                print(f"[STARTUP] Matched Config '{r_name}' (Serial {target_id}) to Physical Index {idx}")
            else:
                if target_id:
                     print(f"[STARTUP] Warning: Configured Serial {target_id} not found in scan. Driver may fail.")

            threading.Thread(
                target=rtl_loop,
                args=(radio, mqtt_handler, processor, sys_id, sys_model),
                daemon=True,
            ).start()
            
            print("[STARTUP] Staggering next radio start by 5 seconds...")
            time.sleep(5)
            
    else:
        # --- AUTO MODE (Simple) ---
        if detected_devices:
            # Pick ONLY the first detected device (Single Device Mode)
            target_radio = detected_devices[0]
            
            print(f"[STARTUP] Auto-detected {len(detected_devices)} radios.")
            print(f"[STARTUP] Unconfigured Mode: Selecting first device only ({target_radio['name']}).")
            
            # Merge defaults
            radio_setup = {
                "freq": config.RTL_DEFAULT_FREQ,
                "hop_interval": config.RTL_DEFAULT_HOP_INTERVAL,
                "rate": config.RTL_DEFAULT_RATE
            }
            radio_setup.update(target_radio)

            threading.Thread(
                target=rtl_loop,
                args=(radio_setup, mqtt_handler, processor, sys_id, sys_model),
                daemon=True,
            ).start()
                
        else:
            # FALLBACK
            print("[STARTUP] No serials detected. Defaulting to generic device '0'.")
            auto_radio = {
                "name": "RTL_auto", 
                "id": "0",
                "freq": config.RTL_DEFAULT_FREQ,             
                "hop_interval": config.RTL_DEFAULT_HOP_INTERVAL,
                "rate": config.RTL_DEFAULT_RATE
            }

            threading.Thread(
                target=rtl_loop,
                args=(auto_radio, mqtt_handler, processor, sys_id, sys_model),
                daemon=True,
            ).start()

    # 6. START SYSTEM MONITOR
    threading.Thread(
        target=system_stats_loop, 
        args=(mqtt_handler, sys_id, sys_model), 
        daemon=True
    ).start()

    # 7. MAIN LOOP
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping MQTT...")
        mqtt_handler.stop()

if __name__ == "__main__":
    main()