"""
FILE: rtl_manager.py
DESCRIPTION:
  Manages the 'rtl_433' subprocess interactions.
  - Fixes IndentationError in the main loop.
"""
import subprocess
import json
import time
import fnmatch
import threading
import sys
import os
import signal
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
    # Scan up to 8 indexes
    while index < 8:
        try:
            # -d index is standard for rtl_eeprom to query a device
            proc = subprocess.run(
                ["rtl_eeprom", "-d", str(index)],
                capture_output=True, text=True, timeout=5,
            )
        except FileNotFoundError:
            print("[STARTUP] WARNING: rtl_eeprom not found; cannot auto-detect.")
            break
        
        output = (proc.stdout or "") + (proc.stderr or "")
        
        # rtl_eeprom returns text even on failure, check for "No supported devices"
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
            # If command succeeded but we couldn't parse serial, add generic
            if proc.returncode == 0:
                devices.append({"name": f"RTL_Index_{index}", "id": str(index), "index": index})

        index += 1
    return devices

def rtl_loop(radio_config: dict, mqtt_handler, data_processor, sys_id: str, sys_model: str) -> None:
    """
    Main loop that spawns rtl_433 and processes its JSON output.
    """
    radio_name = radio_config.get("name", "Unknown")
    radio_id = radio_config.get("id", "0")
    
    # 1. Build Command
    cmd = ["rtl_433", "-F", "json"]

    # Device selection (-d)
    # If we have a mapped index (from discovery), use it. Otherwise use the raw ID.
    dev_index = radio_config.get("index")
    if dev_index is not None:
        cmd.extend(["-d", str(dev_index)])
    else:
        # Fallback: try using the ID directly (works if ID is a simple index '0')
        cmd.extend(["-d", str(radio_id)])

    # Frequency (-f)
    freq_str = str(radio_config.get("freq", config.RTL_DEFAULT_FREQ))
    frequencies = [f.strip() for f in freq_str.split(",")]
    
    # If hopping, use multiple -f. If single, just one -f.
    # rtl_433 handles hopping if multiple -f are passed.
    for f in frequencies:
        cmd.extend(["-f", f])

    # Hop Interval (-H)
    hop_interval = radio_config.get("hop_interval", config.RTL_DEFAULT_HOP_INTERVAL)
    
    # --- NEW LOGIC: Auto-enable hopping if needed ---
    if len(frequencies) > 1:
        # If user provided multiple freqs but hop is 0, default to 60s
        if hop_interval <= 0:
            hop_interval = 60
        cmd.extend(["-H", str(hop_interval)])

    # Sample Rate (-s)
    rate = radio_config.get("rate", config.RTL_DEFAULT_RATE)
    cmd.extend(["-s", rate])

    # Protocols (-R)
    # Default to all (usually omitted implies all), but user might specify specific ones
    protocols = radio_config.get("protocols", [])
    if protocols:
        for p in protocols:
            cmd.extend(["-R", str(p)])
            
    # Extra Arguments (-X, etc)
    # (Add any specific extra args here if needed)

    # Convert settings for display
    freq_display = ",".join(frequencies)

    print(f"[RTL] Starting {radio_name} on {freq_display} (Rate: {rate})...")

    while True:
        process = None
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Capture stderr to hide noise unless needed
                text=True,
                bufsize=1  # Line buffered
            )
            ACTIVE_PROCESSES.append(process)

            # --- READ LOOP ---
            while True:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break # Process died
                    continue

                try:
                    data = json.loads(line)
                    if config.DEBUG_RAW_JSON:
                        # "DEBUG" tag triggers the colorizer in main.py
                        print(f"[DEBUG] {line.strip()}")
                    # 1. Basic Extraction
                    model = data.get("model", "Unknown")
                    raw_id = data.get("id", "Unknown")
                    clean_id = clean_mac(raw_id)
                    dev_name = f"{model} {clean_id}"
                    dev_type = data.get("type", "Untyped")

                    # 2. Check Blacklist
                    if is_blocked_device(clean_id, model, dev_type):
                        continue

                    # 3. Check Whitelist (if enabled)
                    whitelist = getattr(config, "DEVICE_WHITELIST", [])
                    if whitelist:
                        # If whitelist exists, device MUST be in it
                        if not any(fnmatch.fnmatch(clean_id, p) for p in whitelist):
                            continue

                    # 4. Filter Invalid timestamps
                    if "time" in data:
                        # (Optional) Verify time drift if needed
                        pass
                    
                    # --- 5. SPECIAL DEVICE HANDLERS ---
                    
                    # Neptune R900 Water Meter
                    if "Neptune-R900" in model and data.get("consumption") is not None:
                        real_val = float(data["consumption"]) / 10.0
                        data_processor.dispatch_reading(
                            clean_id, "meter_reading", real_val, dev_name, model, 
                            radio_name=radio_name, radio_freq=freq_display
                        )
                        del data["consumption"] # Prevent duplicate sending

                    # SCM / ERT Meters
                    if ("SCM" in model or "ERT" in model) and data.get("consumption") is not None:
                        data_processor.dispatch_reading(
                            clean_id, "Consumption", data["consumption"], dev_name, model,
                            radio_name=radio_name, radio_freq=freq_display
                        )
                        del data["consumption"]

                    # Calculate Dew Point if possible
                    t_c = data.get("temperature_C")
                    if t_c is None and "temperature_F" in data:
                        t_c = (data["temperature_F"] - 32) * 5/9

                    if t_c is not None and data.get("humidity") is not None:
                        dp_f = calculate_dew_point(t_c, data["humidity"])
                        if dp_f is not None:
                            data_processor.dispatch_reading(
                                clean_id, "dew_point", dp_f, dev_name, model,
                                radio_name=radio_name, radio_freq=freq_display
                            )

                    # --- 6. GENERIC FLATTEN & SEND ---
                    flat = flatten(data)
                    for key, value in flat.items():
                        if key in getattr(config, 'SKIP_KEYS', []): continue
                        
                        # Normalize Temperature to Fahrenheit for display
                        if key in ["temperature_C", "temp_C"] and isinstance(value, (int, float)):
                            val_f = round(value * 1.8 + 32.0, 1)
                            data_processor.dispatch_reading(
                                clean_id, "temperature", val_f, dev_name, model,
                                radio_name=radio_name, radio_freq=freq_display
                            )
                        elif key in ["temperature_F", "temp_F", "temperature"] and isinstance(value, (int, float)):
                            data_processor.dispatch_reading(
                                clean_id, "temperature", value, dev_name, model,
                                radio_name=radio_name, radio_freq=freq_display
                            )
                        else:
                            # Catch-all dispatch
                            data_processor.dispatch_reading(
                                clean_id, key, value, dev_name, model,
                                radio_name=radio_name, radio_freq=freq_display
                            )

                except json.JSONDecodeError:
                    # Not a JSON line (maybe startup text), ignore
                    pass
                except Exception as e:
                    print(f"[RTL] Error processing line: {e}")

        except Exception as e:
            print(f"[RTL] Subprocess crashed or failed to start: {e}")
        
        # Cleanup before restart
        if process:
            if process in ACTIVE_PROCESSES:
                ACTIVE_PROCESSES.remove(process)
            process.terminate()
            try:
                process.wait(timeout=2)
            except:
                process.kill()

        print(f"[RTL] {radio_name} crashed/stopped. Restarting in 5s...")
        time.sleep(5)
