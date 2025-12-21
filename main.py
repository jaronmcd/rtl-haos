#!/usr/bin/env python3
"""
FILE: main.py
DESCRIPTION:
  The main executable script.
  - UPDATED: Warnings now include the Radio Name for clarity.
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
    clean = clean_text.lower()
    if "mqtt" in clean: return c_magenta
    if "rtl" in clean: return c_magenta
    if "startup" in clean: return c_magenta
    if "nuke" in clean: return c_red
    return c_cyan

def highlight_json(text):
    text = re.sub(r'("[^"]+")\s*:', f'{c_cyan}\\1{c_reset}{c_white}:{c_reset}', text)
    text = re.sub(r':\s*("[^"]+")', f': {c_white}\\1{c_reset}', text)
    text = re.sub(r':\s*(-?\d+\.?\d*)', f': {c_white}\\1{c_reset}', text)
    text = re.sub(r':\s*(true|false|null)', f': {c_white}\\1{c_reset}', text)
    return text

def timestamped_print(*args, **kwargs):
    now = datetime.now().strftime("%H:%M:%S")
    time_prefix = f"{c_dim}[{now}]{c_reset}"
    msg = " ".join(map(str, args))
    lower_msg = msg.lower()
    
    header = f"{c_green}INFO{c_reset}{c_white}:{c_reset}" 
    special_formatting_applied = False
    
    if any(x in lower_msg for x in ["error", "critical", "failed", "crashed"]):
        header = f"{c_red}ERROR{c_reset}{c_white}:{c_reset}"
        msg = msg.replace("CRITICAL:", "").replace("ERROR:", "").strip()
    elif "warning" in lower_msg:
        header = f"{c_yellow}WARN{c_reset}{c_white}:{c_reset}"
        msg = msg.replace("WARNING:", "").strip()
    elif "debug" in lower_msg:
        header = f"{c_magenta}DEBUG{c_reset}{c_white}:{c_reset}"
        msg = msg.replace("[DEBUG]", "").replace("[debug]", "").strip()
        if "{" in msg and "}" in msg: msg = highlight_json(msg)
    elif "-> tx" in lower_msg:
        header = f"{c_green}DATA{c_reset}{c_white}:{c_reset}"
        msg = msg.replace("-> TX", "").strip()
        match = re.match(r".*?\[(.*?)(?:\])?:\s+(.*)", msg)
        if match:
            src_text = match.group(1).replace("]", "")
            val = match.group(2)
            msg = f"{c_white}[{c_reset}{c_cyan}{src_text}{c_reset}{c_white}]:{c_reset} {c_white}{val}{c_reset}"
            special_formatting_applied = True

    if not special_formatting_applied:
        match = re.match(r"^\[(.*?)\]\s*(.*)", msg)
        if match:
            src_text = match.group(1)
            rest_of_msg = match.group(2)
            rest_of_msg = re.sub(r"^(RX:?|:)\s*", "", rest_of_msg).strip()
            s_color = get_source_color(src_text)
            msg = f"{c_white}[{c_reset}{s_color}{src_text}{c_reset}{c_white}]:{c_reset} {rest_of_msg}"

    _original_print(f"{time_prefix} {header} {msg}", flush=True, **kwargs)

builtins.print = timestamped_print

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
from utils import get_system_mac, validate_radio_config
from system_monitor import system_stats_loop
from data_processor import DataProcessor
from rtl_manager import rtl_loop, discover_rtl_devices

def get_version():
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.yaml")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                for line in f:
                    if line.strip().startswith("version:"):
                        return f"v{line.split(':', 1)[1].strip().replace('\"', '').replace('\'', '')}"
    except Exception:
        pass
    return "Unknown"

def show_logo(version):
    logo_lines = [
        r"   ____  _____  _         _   _    _    ___  ____  ",
        r"  |  _ \|_   _|| |       | | | |  / \  / _ \/ ___| ",
        r"  | |_) | | |  | |  ___  | |_| | / _ \| | | \___ \ ",
        r"  |  _ <  | |  | | |___| |  _  |/ ___ \ |_| |___) |",
        r"  |_| \_\ |_|  |_____|   |_| |_/_/   \_\___/|____/ "
    ]
    for line in logo_lines: sys.stdout.write(f"{c_blue}{line}{c_reset}\n")
    sys.stdout.write(f"\n{c_cyan}>>> RTL-SDR Bridge for Home Assistant ({c_reset}{c_yellow}{version}{c_reset}{c_cyan}) <<<{c_reset}\n\n\n")
    sys.stdout.flush()

def main():
    ver = get_version()
    show_logo(ver)
    time.sleep(3)

    mqtt_handler = HomeNodeMQTT(version=ver)
    mqtt_handler.start()

    processor = DataProcessor(mqtt_handler)
    threading.Thread(target=processor.start_throttle_loop, daemon=True).start()

    sys_id = get_system_mac().replace(":", "").lower() 
    sys_model = config.BRIDGE_NAME
    
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

    rtl_config = getattr(config, "RTL_CONFIG", None)

    if rtl_config:
        # --- A. MANUAL CONFIGURATION MODE ---
        print(f"[STARTUP] Loading {len(rtl_config)} radios from manual config.")
        configured_ids = set()

        for radio in rtl_config:
            # --- UPDATED: Get Name First for clearer Warning ---
            r_name = radio.get("name", "Unknown")
            
            warns = validate_radio_config(radio)
            for w in warns:
                print(f"[STARTUP] CONFIG WARNING: [Radio: {r_name}] {w}")
            # ---------------------------

            target_id = radio.get("id") 
            if target_id: target_id = str(target_id).strip()
            
            if target_id and target_id in serial_to_index:
                idx = serial_to_index[target_id]
                radio['index'] = idx
                configured_ids.add(target_id)
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
            
        if detected_devices:
            for d in detected_devices:
                d_id = str(d.get("id"))
                if d_id not in configured_ids:
                    print(f"[STARTUP] WARNING: Radio (Serial {d_id}) detected but NOT configured. It is currently idle.")
            
    else:
        # --- B. SMART AUTO-CONFIGURATION MODE ---
        if detected_devices:
            print(f"[STARTUP] Auto-detected {len(detected_devices)} radios.")
            print(f"[STARTUP] Unconfigured Mode: Starting PRIMARY radio only.")

            dev = detected_devices[0]
            dev_name = dev.get("name", "Primary")

            # 1. SMART DEFAULT LOGIC
            def_freqs = config.RTL_DEFAULT_FREQ.split(",")
            def_hop = config.RTL_DEFAULT_HOP_INTERVAL
            if len(def_freqs) < 2: def_hop = 0

            radio_setup = {
                "hop_interval": def_hop,
                "rate": config.RTL_DEFAULT_RATE,
                "freq": config.RTL_DEFAULT_FREQ
            }
            
            warns = validate_radio_config(radio_setup)
            for w in warns:
                print(f"[STARTUP] DEFAULT CONFIG WARNING: [Radio: {dev_name}] {w}")
            
            print(f"[STARTUP] Radio #1 ({dev['name']}) -> Defaulting to {radio_setup['freq']}")
            
            if len(detected_devices) > 1:
                print(f"[STARTUP] WARNING: {len(detected_devices)-1} other device(s) ignored in auto-mode. Configure them in options.json to use.")

            radio_setup.update(dev)

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
            
            warns = validate_radio_config(auto_radio)
            for w in warns:
                print(f"[STARTUP] CONFIG WARNING: [Radio: RTL_auto] {w}")

            threading.Thread(
                target=rtl_loop,
                args=(auto_radio, mqtt_handler, processor, sys_id, sys_model),
                daemon=True,
            ).start()

    threading.Thread(target=system_stats_loop, args=(mqtt_handler, sys_id, sys_model), daemon=True).start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping MQTT...")
        mqtt_handler.stop()

if __name__ == "__main__":
    main()