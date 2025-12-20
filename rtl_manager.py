"""
FILE: rtl_manager.py
DESCRIPTION:
  Manages the 'rtl_433' subprocess interactions.
  - UPDATED: Now passes 'radio_name' to data_processor for better logging.
"""
import subprocess
import json
import time
import fnmatch
import threading
from datetime import datetime
import config
from utils import clean_mac, calculate_dew_point

# --- Process Tracking ---
ACTIVE_PROCESSES = []

def trigger_radio_restart():
    """Terminates all running radios."""
    print("[RTL] User requested restart. Stopping processes...")
    for p in list(ACTIVE_PROCESSES):
        if p.poll() is None:
            p.terminate()

def flatten(d, sep="_") -> dict:
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

def is_blocked_device(clean_id: str, model: str, dev_type: str) -> bool:
    """Checks against Blacklist in config."""
    patterns = getattr(config, "DEVICE_BLACKLIST", [])
    for pattern in patterns:
        if fnmatch.fnmatch(str(clean_id), pattern): return True
        if fnmatch.fnmatch(str(model), pattern): return True
        if fnmatch.fnmatch(str(dev_type), pattern): return True
    return False

def discover_rtl_devices():
    devices = []
    index = 0
    while index < 8:
        try:
            proc = subprocess.run(
                ["rtl_eeprom", "-d", str(index)],
                capture_output=True, text=True, timeout=5,
            )
        except FileNotFoundError:
            print("[STARTUP] WARNING: rtl_eeprom not found; cannot auto-detect.")
            break
        
        output = (proc.stdout or "") + (proc.stderr or "")
        if "No supported devices" in output or "No matching device" in output:
            break

        serial = None
        for line in output.splitlines():
            if "Serial number" in line or "serial number" in line or "S/N" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    candidate = parts[1].strip()
                    if candidate:
                        serial = candidate.split()[0]
                        break
        
        if serial:
            print(f"[STARTUP] Found RTL-SDR at index {index}: Serial {serial}")
            devices.append({"name": f"RTL_{serial}", "id": serial, "index": index})
        else:
            if proc.returncode == 0:
                devices.append({"name": f"RTL_Index_{index}", "id": str(index), "index": index})

        index += 1
    return devices

# FILE: rtl_manager.py (Partial)

def rtl_loop(radio_config: dict, mqtt_handler, data_processor, sys_id: str, sys_model: str) -> None:
    # ... (existing setup) ...
    
    # 1. Prepare the Frequency String (e.g., "433.92M" or "433M,915M")
    freq_display = ",".join(frequencies)

    # ... (inside the while True loop, processing lines) ...

                    # ... (Parsing JSON data) ...

                    # UPDATED: Pass radio_freq=freq_display to all calls below
                    
                    if "Neptune-R900" in model and data.get("consumption") is not None:
                        real_val = float(data["consumption"]) / 10.0
                        data_processor.dispatch_reading(clean_id, "meter_reading", real_val, dev_name, model, radio_name=radio_name, radio_freq=freq_display)
                        del data["consumption"]

                    if ("SCM" in model or "ERT" in model) and data.get("consumption") is not None:
                        data_processor.dispatch_reading(clean_id, "Consumption", data["consumption"], dev_name, model, radio_name=radio_name, radio_freq=freq_display)
                        del data["consumption"]

                    # ... (Temperature/Humidity logic) ...

                    if t_c is not None and data.get("humidity") is not None:
                        dp_f = calculate_dew_point(t_c, data["humidity"])
                        if dp_f is not None:
                            data_processor.dispatch_reading(clean_id, "dew_point", dp_f, dev_name, model, radio_name=radio_name, radio_freq=freq_display)

                    flat = flatten(data)
                    for key, value in flat.items():
                        if key in getattr(config, 'SKIP_KEYS', []): continue
                        
                        if key in ["temperature_C", "temp_C"] and isinstance(value, (int, float)):
                            val_f = round(value * 1.8 + 32.0, 1)
                            data_processor.dispatch_reading(clean_id, "temperature", val_f, dev_name, model, radio_name=radio_name, radio_freq=freq_display)
                        elif key in ["temperature_F", "temp_F", "temperature"] and isinstance(value, (int, float)):
                            data_processor.dispatch_reading(clean_id, "temperature", value, dev_name, model, radio_name=radio_name, radio_freq=freq_display)
                        else:
                            # Catch-all dispatch
                            data_processor.dispatch_reading(clean_id, key, value, dev_name, model, radio_name=radio_name, radio_freq=freq_display)