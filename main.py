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
  - UPDATED: Auto-discovery logic:
      Radio 1 -> 433.92M
      Radio 2 -> 915M (1000k)
      Radio 3+ -> Defaults to 433.92M + "Suggest Manual Config" log.
"""
import os
import sys
import re

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
# Standard ANSI with Bold (1;) to force "Bright" colors on HAOS.

c_cyan    = "\033[1;36m"   # Bold Cyan (Radio IDs / JSON Keys)
c_magenta = "\033[1;35m"   # Bold Magenta (System Tags / DEBUG Header)
c_blue    = "\033[1;34m"   # Bold Blue (JSON Numbers / Infrastructure)
c_green   = "\033[1;32m"   # Bold Green (DATA Header / INFO)
c_yellow  = "\033[1;33m"   # Bold Yellow (WARN Only)
c_red     = "\033[1;31m"   # Bold Red (ERROR)
c_white   = "\033[1;37m"   # Bold White (Values / Brackets / Colons)
c_dim     = "\033[37m"     # Standard White (Timestamp)
c_reset   = "\033[0m"

_original_print = builtins.print

def get_source_color(clean_text):
    """
    Determines the color of the source tag text (without brackets).
    """
    clean = clean_text.lower()
    
    # Infrastructure -> Magenta
    if "mqtt" in clean: return c_magenta
    if "rtl" in clean: return c_magenta
    if "startup" in clean: return c_magenta
    if "nuke" in clean: return c_red
    
    # Radio Data / IDs -> Cyan
    return c_cyan

def highlight_json(text):
    """
    Simple Regex-based JSON syntax highlighter.
    Keys = Cyan
    Values = White
    Separators = White
    """
    # 1. Color Keys (Strings followed by colon) -> Cyan key, White Colon
    text = re.sub(r'("[^"]+")\s*:', f'{c_cyan}\\1{c_reset}{c_white}:{c_reset}', text)
    
    # 2. Color Values (String, Number, Bool) -> White
    text = re.sub(r':\s*("[^"]+")', f': {c_white}\\1{c_reset}', text)
    text = re.sub(r':\s*(-?\d+\.?\d*)', f': {c_white}\\1{c_reset}', text)
    text = re.sub(r':\s*(true|false|null)', f': {c_white}\\1{c_reset}', text)
    
    return text

def timestamped_print(*args, **kwargs):
    """
    Smart Logging v27 (Purple Debug):
    DEBUG header is now Magenta.
    """
    now = datetime.now().strftime("%H:%M:%S")
    time_prefix = f"{c_dim}[{now}]{c_reset}"
    
    msg = " ".join(map(str, args))
    lower_msg = msg.lower()
    
    # --- 1. DETERMINE HEADER LEVEL ---
    # Default: Green INFO + White Colon
    header = f"{c_green}INFO{c_reset}{c_white}:{c_reset}" 
    special_formatting_applied = False
    
    # A. ERROR (Red + White Colon)
    if any(x in lower_msg for x in ["error", "critical", "failed", "crashed"]):
        header = f"{c_red}ERROR{c_reset}{c_white}:{c_reset}"
        msg = msg.replace("CRITICAL:", "").replace("ERROR:", "").strip()

    # B. WARNING (Yellow + White Colon)
    elif "warning" in lower_msg:
        header = f"{c_yellow}WARN{c_reset}{c_white}:{c_reset}"
        msg = msg.replace("WARNING:", "").strip()

    # C. DEBUG (Purple/Magenta + White Colon)
    elif "debug" in lower_msg:
        header = f"{c_magenta}DEBUG{c_reset}{c_white}:{c_reset}"
        msg = msg.replace("[DEBUG]", "").replace("[debug]", "").strip()
        
        # Apply JSON Highlighting
        if "{" in msg and "}" in msg:
            msg = highlight_json(msg)

    # D. DATA (Green Header + White Colon)
    elif "-> tx" in lower_msg:
        header = f"{c_green}DATA{c_reset}{c_white}:{c_reset}"
        msg = msg.replace("-> TX", "").strip()
        
        # Parse specialized format: "rtl-bridge... [source]: value"
        match = re.match(r".*?\[(.*?)(?:\])?:\s+(.*)", msg)
        if match:
            src_text = match.group(1).replace("]", "")
            val = match.group(2)
            
            # Format: White[ CyanSource White]: WhiteValue
            msg = f"{c_white}[{c_reset}{c_cyan}{src_text}{c_reset}{c_white}]:{c_reset} {c_white}{val}{c_reset}"
            special_formatting_applied = True

    # --- 2. UNIVERSAL SOURCE DETECTION ---
    if not special_formatting_applied:
        # Regex catches [Content] at start of message
        match = re.match(r"^\[(.*?)\]\s*(.*)", msg)
        if match:
            src_text = match.group(1)
            rest_of_msg = match.group(2)
            
            # Clean "RX:" and existing colons
            rest_of_msg = re.sub(r"^(RX:?|:)\s*", "", rest_of_msg).strip()
            
            # Determine Color
            s_color = get_source_color(src_text)
            
            # Format: White[ ColorSource White]: Message
            msg = f"{c_white}[{c_reset}{s_color}{src_text}{c_reset}{c_white}]:{c_reset} {rest_of_msg}"

    # Print Final
    _original_print(f"{time_prefix} {header} {msg}", flush=True, **kwargs)

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
    """Prints the ASCII logo (Blue) and Subtitle (Cyan/Yellow)."""
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
    
    # 3. Print Subtitle: Cyan & Yellow
    sys.stdout.write(
        f"{c_cyan}>>> RTL-SDR Bridge for Home Assistant ({c_reset}"
        f"{c_yellow}{version}{c_reset}"
        f"{c_cyan}) <<<{c_reset}\n"
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
        # --- A. MANUAL CONFIGURATION MODE ---
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
        # --- B. SMART AUTO-CONFIGURATION MODE ---
        if detected_devices:
            print(f"[STARTUP] Auto-detected {len(detected_devices)} radios.")
            print(f"[STARTUP] Unconfigured Mode: Auto-assigning frequencies...")

            for i, dev in enumerate(detected_devices):
                # 1. Base Setup
                radio_setup = {
                    "hop_interval": config.RTL_DEFAULT_HOP_INTERVAL,
                    "rate": config.RTL_DEFAULT_RATE
                }
                
                # 2. Smart Logic: Radio 1 = 433, Radio 2 = 915, Others = Default
                if i == 0:
                    radio_setup["freq"] = config.RTL_DEFAULT_FREQ # Default 433.92M
                    print(f"[STARTUP] Radio #{i+1} ({dev['name']}) -> Defaulting to {radio_setup['freq']}")
                elif i == 1:
                    radio_setup["freq"] = "915M"
                    radio_setup["rate"] = "1000k"
                    print(f"[STARTUP] Radio #{i+1} ({dev['name']}) -> Auto-Setting to 915M (1000k)")
                else:
                    # Fallback for Radio 3+
                    radio_setup["freq"] = config.RTL_DEFAULT_FREQ
                    print(f"[STARTUP] Radio #{i+1} ({dev['name']}) -> Defaulting to {radio_setup['freq']}")
                    print(f"[STARTUP] Hint: If this device is for 315M or 868M, please configure it manually in options.")

                # 3. Merge Device Info and Launch
                radio_setup.update(dev)

                threading.Thread(
                    target=rtl_loop,
                    args=(radio_setup, mqtt_handler, processor, sys_id, sys_model),
                    daemon=True,
                ).start()
                
                # Stagger startup to avoid USB power spikes
                time.sleep(5)
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