#!/usr/bin/env python3
"""
FILE: rtl_mqtt_bridge.py
DESCRIPTION:
  The main executable script.
  - UPDATED: Groups "Radio Status" under the main System/Computer device.
"""
import subprocess
import json
import time
import threading
import sys
import importlib.util
import fnmatch
import re
import socket
import statistics 
from rich import print


# --- PRE-FLIGHT DEPENDENCY CHECK ---
def check_dependencies():
    # 1. Check for the rtl_433 binary (System Dependency)
    if not subprocess.run(["which", "rtl_433"], capture_output=True).stdout:
        print("CRITICAL: 'rtl_433' binary not found. Please install it (e.g., sudo apt install rtl-433).")
        sys.exit(1)

    # 2. Check for Paho MQTT (Python Dependency)
    if importlib.util.find_spec("paho") is None:
        print("CRITICAL: Python dependency 'paho-mqtt' not found.")
        print("Please install requirements: pip install -r requirements.txt")
        sys.exit(1)

check_dependencies()

import paho.mqtt.client as mqtt
import config
from utils import clean_mac, calculate_dew_point, get_system_mac
from mqtt_handler import HomeNodeMQTT
from field_meta import FIELD_META 
from system_monitor import system_stats_loop

# --- BUFFER GLOBALS ---
DATA_BUFFER = {} 
BUFFER_LOCK = threading.Lock()

# ---------------- HELPERS ----------------
def flatten(d, sep: str = "_") -> dict:
    obj = {}
    def recurse(t, parent: str = ""):
        if isinstance(t, list):
            for i, v in enumerate(t):
                recurse(v, f"{parent}{sep}{i}" if parent else str(i))
        elif isinstance(t, dict):
            for k, v in t.items():
                recurse(v, f"{parent}{sep}{k}" if parent else k)
        else:
            if parent: obj[parent] = t
    recurse(d)
    return obj

def is_blocked_device(clean_id: str, model: str) -> bool:
    patterns = getattr(config, "DEVICE_BLACKLIST", None)
    if not patterns: return False
    for pattern in patterns:
        if fnmatch.fnmatch(str(clean_id), pattern): return True
        if fnmatch.fnmatch(str(model), pattern): return True
    return False

# ---------------- BUFFERING / DISPATCH ----------------
def dispatch_reading(clean_id, field, value, dev_name, model, mqtt_handler):
    interval = getattr(config, "RTL_THROTTLE_INTERVAL", 0)
    if interval <= 0:
        mqtt_handler.send_sensor(clean_id, field, value, dev_name, model, is_rtl=True)
        return

    with BUFFER_LOCK:
        if clean_id not in DATA_BUFFER:
            DATA_BUFFER[clean_id] = {}
        if "__meta__" not in DATA_BUFFER[clean_id]:
            DATA_BUFFER[clean_id]["__meta__"] = {"name": dev_name, "model": model}
        if field not in DATA_BUFFER[clean_id]:
            DATA_BUFFER[clean_id][field] = []
        DATA_BUFFER[clean_id][field].append(value)

def throttle_flush_loop(mqtt_handler):
    interval = getattr(config, "RTL_THROTTLE_INTERVAL", 30)
    if interval <= 0: return

    print(f"[THROTTLE] Averaging data every {interval} seconds.")
    while True:
        time.sleep(interval)
        with BUFFER_LOCK:
            if not DATA_BUFFER: continue
            current_batch = DATA_BUFFER.copy()
            DATA_BUFFER.clear()

        count_sent = 0
        for clean_id, device_data in current_batch.items():
            meta = device_data.get("__meta__", {})
            dev_name = meta.get("name", "Unknown")
            model = meta.get("model", "Unknown")

            for field, values in device_data.items():
                if field == "__meta__": continue
                if not values: continue

                final_val = None
                try:
                    if isinstance(values[0], (int, float)):
                        final_val = round(statistics.mean(values), 2)
                        if final_val.is_integer(): final_val = int(final_val)
                    else:
                        final_val = values[-1]
                except:
                    final_val = values[-1]

                mqtt_handler.send_sensor(clean_id, field, final_val, dev_name, model, is_rtl=True)
                count_sent += 1
        
        if getattr(config, "DEBUG_RAW_JSON", False) and count_sent > 0:
            print(f"[THROTTLE] Flushed {count_sent} averaged readings.")

def discover_default_rtl_serial():
    """
    Try to read the serial number of the default RTL-SDR using rtl_eeprom.
    Returns the serial string, or None if it can't be determined.
    """
    try:
        proc = subprocess.run(
            ["rtl_eeprom"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        print("[STARTUP] rtl_eeprom not found; cannot auto-detect RTL-SDR serial.")
        return None
    except Exception as e:
        print(f"[STARTUP] Error running rtl_eeprom: {e}")
        return None

    output = (proc.stdout or "") + (proc.stderr or "")
    serial = None

    for line in output.splitlines():
        line = line.strip()
        # Typical lines contain "Serial number:" or "S/N:"
        if "Serial number" in line or "serial number" in line or "S/N" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                candidate = parts[1].strip()
                if candidate:
                    serial = candidate.split()[0]
                    break

    if serial:
        return serial

    print("[STARTUP] Could not parse RTL-SDR serial from rtl_eeprom output.")
    return None
# rtl_mqtt_bridge.py (Partial - replace only the rtl_loop function)

def rtl_loop(radio_config: dict, mqtt_handler: HomeNodeMQTT, sys_id: str, sys_model: str) -> None:
    # Radio Config
    rtl_433_cmd = radio_config.get("rtl_433_cmd", "rtl_433")
    device_id = radio_config.get("id", "0")
    frequency = radio_config.get("freq", "433.92M")
    hop_interval = radio_config.get("hop_interval", "20")
    radio_name = radio_config.get("name", f"RTL_{device_id}")
    sample_rate = radio_config.get("rate", "250k")
    raw_params = radio_config.get("raw_params", "")

    # --- Names & IDs ---
    # The internal field name (used for topic/unique_id)
    status_field = f"radio_status_{device_id}"
    
    # The Friendly Name for Home Assistant (e.g. "Weather Radio Status")
    status_friendly_name = f"{radio_name}"

    # System name (used for device grouping)
    sys_name = f"{sys_model} ({sys_id})"

    # CMD
    cmd = [
        rtl_433_cmd,  "-s", sample_rate, "-F", "json",
        "-M", "time:iso", "-M", "protocol", "-M", "level",
    ]

    for freq in frequency.split(","):
        cmd.extend(["-f", freq.strip()])

    if hop_interval.strip():
        cmd.extend(["-H", hop_interval.strip()])

    if raw_params:
        for raw in re.sub(r"\s+", " ", raw_params.strip()).split(" "):
            cmd.append(raw.strip())

    print(f"[RTL] Manager started for {radio_name}. Monitoring...")

    while True:
        # 1. Announce "Scanning" with custom Friendly Name
        mqtt_handler.send_sensor(
            sys_id, status_field, "Scanning...", sys_name, sys_model, 
            is_rtl=True, friendly_name=status_friendly_name
        )
        time.sleep(2)

        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

            for line in proc.stdout:
                if not line: continue
                safe_line = line.strip()

                # --- ERROR DETECTION ---
                if "usb_open error" in safe_line or "No supported devices" in safe_line:
                    print(f"[{radio_name}] Hardware missing!")
                    mqtt_handler.send_sensor(
                        sys_id, status_field, "No Device Found", sys_name, sys_model, 
                        is_rtl=True, friendly_name=status_friendly_name
                    )
                
                elif "Kernel driver is active" in safe_line or "LIBUSB_ERROR_BUSY" in safe_line:
                    print(f"[{radio_name}] USB Busy/Driver Error!")
                    mqtt_handler.send_sensor(
                        sys_id, status_field, "Error: USB Busy", sys_name, sys_model, 
                        is_rtl=True, friendly_name=status_friendly_name
                    )

                # --- VALID DATA ---
                if safe_line.startswith("{") and safe_line.endswith("}"):
                    try:
                        data = json.loads(safe_line)
                        # STATUS UPDATE: Online
                        mqtt_handler.send_sensor(
                            sys_id, status_field, "Online", sys_name, sys_model, 
                            is_rtl=True, friendly_name=status_friendly_name
                        )
                    except:
                        continue

                    # --- SENSOR PROCESSING (Standard) ---
                    # Note: We do NOT pass friendly_name here, because these are standard sensors
                    # (Temperature, Humidity) that should use the default lookup logic.
                    model = data.get("model", "Generic")
                    sid = data.get("id") or data.get("channel") or "unknown"
                    clean_id = clean_mac(sid)
                    dev_name = f"{model} ({clean_id})"

                    # Filtering
                    whitelist = getattr(config, "DEVICE_WHITELIST", [])
                    if whitelist:
                        is_allowed = False
                        for pattern in whitelist:
                            if fnmatch.fnmatch(str(clean_id), pattern) or fnmatch.fnmatch(model, pattern):
                                is_allowed = True
                                break
                        if not is_allowed: continue
                    else:
                        if is_blocked_device(clean_id, model): continue

                    if getattr(config, "DEBUG_RAW_JSON", False):
                        print(f"[{radio_name}] RX: {safe_line}")

                    # Utilities
                    if "Neptune-R900" in model and data.get("consumption") is not None:
                        real_val = float(data["consumption"]) / 10.0
                        dispatch_reading(clean_id, "meter_reading", real_val, dev_name, model, mqtt_handler)
                        del data["consumption"]

                    if ("SCM" in model or "ERT" in model) and data.get("consumption") is not None:
                        dispatch_reading(clean_id, "Consumption", data["consumption"], dev_name, model, mqtt_handler)
                        del data["consumption"]

                    # Dew Point
                    t_c = None
                    if "temperature_C" in data: t_c = data["temperature_C"]
                    elif "temp_C" in data: t_c = data["temp_C"]
                    elif "temperature_F" in data: t_c = (data["temperature_F"] - 32.0) * 5.0 / 9.0
                    elif "temperature" in data: t_c = data["temperature"]

                    if t_c is not None and data.get("humidity") is not None:
                        dp_f = calculate_dew_point(t_c, data["humidity"])
                        if dp_f is not None:
                            dispatch_reading(clean_id, "dew_point", dp_f, dev_name, model, mqtt_handler)

                    # Flatten & Send
                    flat = flatten(data)
                    for key, value in flat.items():
                        if key in getattr(config, 'SKIP_KEYS', []): continue
                        if key in ["temperature_C", "temp_C"] and isinstance(value, (int, float)):
                            val_f = round(value * 1.8 + 32.0, 1)
                            dispatch_reading(clean_id, "temperature", val_f, dev_name, model, mqtt_handler)
                        elif key in ["temperature_F", "temp_F", "temperature"] and isinstance(value, (int, float)):
                            dispatch_reading(clean_id, "temperature", value, dev_name, model, mqtt_handler)
                        else:
                            dispatch_reading(clean_id, key, value, dev_name, model, mqtt_handler)

            if proc: proc.wait()
            if proc.returncode != 0:
                print(f"[{radio_name}] Process exited with code {proc.returncode}")
                print(subprocess.list2cmdline(cmd))
                mqtt_handler.send_sensor(
                    sys_id, status_field, "Error: Crashed", sys_name, sys_model, 
                    is_rtl=True, friendly_name=status_friendly_name
                )

        except Exception as e:
            print(f"[{radio_name}] Exception: {e}")
            mqtt_handler.send_sensor(
                sys_id, status_field, "Script Error", sys_name, sys_model, 
                is_rtl=True, friendly_name=status_friendly_name
            )

        print(f"[{radio_name}] Retrying in 30 seconds...")
        time.sleep(30)

def main():
    print("--- RTL-MQTT BRIDGE + SYSTEM MONITOR STARTING ---")

    mqtt_handler = HomeNodeMQTT()
    mqtt_handler.start()

    # --- 1. GET SYSTEM IDENTITY ---
    # We grab these here so we can pass them to the RTL loop
    sys_id = get_system_mac().replace(":", "").lower()
    sys_model = socket.gethostname().title()

    # --- 2. START RTL THREADS ---
    rtl_config = getattr(config, "RTL_CONFIG", None)

    if rtl_config and len(rtl_config) > 1:
        # Explicit radios from config.py
        for radio in rtl_config:
            threading.Thread(
                target=rtl_loop,
                args=(radio, mqtt_handler, sys_id, sys_model),
                daemon=True,
            ).start()
    else:
        # AUTO MODE: no RTL_CONFIG defined or it's empty/single config.
        # Try to detect the actual RTL-SDR serial so we can use it as the ID.
        auto_serial = discover_default_rtl_serial()

        if auto_serial:
            print(f"[STARTUP] Auto-detected RTL-SDR serial: {auto_serial}")
            auto_radio = {
                "name": f"RTL_{auto_serial}",
                "id": auto_serial,
            }
        else:
            # Fallback if we can't read the serial
            print("[STARTUP] Using default RTL-SDR id '0'")
            auto_radio = {
                "name": "RTL_auto",
                "id": "0",
            }

        auto_radio = auto_radio | rtl_config[0] if rtl_config else {}

        threading.Thread(
            target=rtl_loop,
            args=(auto_radio, mqtt_handler, sys_id, sys_model),
            daemon=True,
        ).start()

    # --- 3. START SYSTEM MONITOR ---
    threading.Thread(target=system_stats_loop, args=(mqtt_handler, sys_id, sys_model), daemon=True).start()

    # --- 4. START THROTTLE FLUSHER ---
    threading.Thread(target=throttle_flush_loop, args=(mqtt_handler,), daemon=True).start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping MQTT...")
        mqtt_handler.stop()

if __name__ == "__main__":
    main()

