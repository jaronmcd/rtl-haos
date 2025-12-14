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
  - UPDATED: Smart Logging (Switches to Yellow WARNING if detected).
"""
import os
import sys

# --- 0. FORCE COLOR ENVIRONMENT ---
os.environ["TERM"] = "xterm-256color"
os.environ["CLICOLOR_FORCE"] = "1"

import builtins
from datetime import datetime
import threading
import time
import importlib.util
import subprocess

# --- 1. GLOBAL LOGGING & COLOR SETUP ---
# Hex codes \x1b are safer for Docker logs
c_blue   = "\x1b[34m"    # Standard Blue
c_purple = "\x1b[35m"    # Standard Purple
c_green  = "\x1b[32m"    # Standard Green
c_yellow = "\x1b[33m"    # Standard Yellow
c_red    = "\x1b[31m"    # Standard Red
c_reset  = "\x1b[0m"

_original_print = builtins.print

def timestamped_print(*args, **kwargs):
    """
    Replica of HAOS Logging format with Level Detection:
    - If message contains "warning", uses Yellow WARNING: tag.
    - If message contains "critical" or "error", uses Red WARNING: tag.
    - Otherwise, uses Green INFO: tag.
    """
    now = datetime.now().strftime("%H:%M:%S")
    msg = " ".join(map(str, args))
    lower_msg = msg.lower()
    
    # Determine Color/Tag based on content
    if "warning" in lower_msg:
        prefix = f"[{now}] {c_yellow}WARNING:{c_reset}"
    elif "critical" in lower_msg or "error" in lower_msg or "failed" in lower_msg or "crashed" in lower_msg:
        prefix = f"[{now}] {c_red}WARNING:{c_reset}"
    else:
        prefix = f"[{now}] {c_green}INFO:{c_reset}"
    
    _original_print(f"{prefix} {msg}", flush=True, **kwargs)

# Override the built-in print
builtins.print = timestamped_print
# ------------------------------------

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
    """Prints the ASCII logo (Blue) and Subtitle (Purple/Yellow)."""
    logo_lines = [
        r"   ____  _____  _         _   _    _    ___  ____  ",
        r"  |  _ \|_   _|| |       | | | |  / \  / _ \/ ___| ",
        r"  | |_) | | |  | |  ___  | |_| | / _ \| | | \___ \ ",
        r"  |  _ <  | |  | | |___| |  _  |/ ___ \ |_| |___) |",
        r"  |_| \_\ |_|  |_____|   |_| |_/_/   \_\___/|____/ "
    ]
    
    # 1. Print Logo: Apply Blue to EACH line individually
    for line in logo_lines:
        sys.stdout.write(f"{c_blue}{line}{c_reset}\n")
    
    # 2. SPACER
    sys.stdout.write("\n")
    
    # 3. Print Subtitle: Purple & Yellow
    sys.stdout.write(
        f"{c_purple}>>> RTL-SDR Bridge for Home Assistant ({c_reset}"
        f"{c_yellow}{version}{c_reset}"
        f"{c_purple}) <<<{c_reset}\n"
    )
    
    # 4. Separator
    sys.stdout.write("\n")
    sys.stdout.write("\n")
    sys.stdout.flush()

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

    # --- HARDWARE MAPPING ---
    print("[STARTUP] Scanning USB bus for RTL-SDR devices...")
    detected_devices = discover_rtl_devices()
    
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
            time.sleep(5)
            
    else:
        if detected_devices:
            target_radio = detected_devices[0]
            print(f"[STARTUP] Auto-detected {len(detected_devices)} radios.")
            print(f"[STARTUP] Unconfigured Mode: Selecting first device only ({target_radio['name']}).")
            
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
            print("[STARTUP] No serials detected. Defaulting to generic device '0'.")
            auto_radio = {
                "name": "RTL_auto", "id": "0",
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