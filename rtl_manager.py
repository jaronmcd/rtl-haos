"""
FILE: rtl_manager.py
DESCRIPTION:
  Manages the 'rtl_433' subprocess interactions.
  - rtl_loop(): The main thread that reads stdout from rtl_433.
  - discover_default_rtl_serial(): Auto-detects USB stick serial numbers.
  - UPDATED: Now supports Frequency Hopping via 'hop_interval' and multiple frequencies.
"""
import subprocess
import json
import time
import fnmatch
import config
from utils import clean_mac, calculate_dew_point

def flatten(d, sep="_") -> dict:
    """Recursively flattens a nested dictionary."""
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
    """Checks against Blacklist in config."""
    patterns = getattr(config, "DEVICE_BLACKLIST", None)
    if not patterns: return False
    for pattern in patterns:
        if fnmatch.fnmatch(str(clean_id), pattern): return True
        if fnmatch.fnmatch(str(model), pattern): return True
    return False

def discover_default_rtl_serial():
    """Attempts to read the serial number of the first connected RTL-SDR."""
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

def rtl_loop(radio_config: dict, mqtt_handler, data_processor, sys_id: str, sys_model: str) -> None:
    """
    Runs the rtl_433 process in a loop.
    Parses JSON output and passes it to data_processor.dispatch_reading().
    """
    # --- Radio Config Parsing ---
    device_id = radio_config.get("id", "0")
    radio_name = radio_config.get("name", f"RTL_{device_id}")
    sample_rate = radio_config.get("rate", "250k")
    
    # 1. Frequency Parsing (Supports list, comma-string, or single string)
    raw_freq = radio_config.get("freq", "433.92M")
    frequencies = []
    
    if isinstance(raw_freq, list):
        frequencies = [str(f) for f in raw_freq]
    else:
        # Handle "433.92M, 315M" or simple "433.92M"
        frequencies = [f.strip() for f in str(raw_freq).split(",")]

    # 2. Hop Interval
    hop_interval = radio_config.get("hop_interval")

    # --- Names & IDs ---
    status_field = f"radio_status_{device_id}"
    status_friendly_name = f"{radio_name}"
    sys_name = f"{sys_model} ({sys_id})"

    # --- Build Command ---
    cmd = ["rtl_433", "-d", f":{device_id}"]

    # Add Frequencies
    for f in frequencies:
        cmd.extend(["-f", f])

    # Add Hop Interval (Only if multiple frequencies exist)
    if len(frequencies) > 1 and hop_interval:
        cmd.extend(["-H", str(hop_interval)])

    # Standard Args
    cmd.extend([
        "-s", sample_rate,
        "-F", "json", "-F", "log", 
        "-M", "time:iso", "-M", "protocol", "-M", "level"
    ])

    print(f"[RTL] Manager started for {radio_name}. Freqs: {frequencies} | Hopping: {hop_interval if len(frequencies)>1 else 'Off'}")

    while True:
        # 1. Announce "Scanning"
        mqtt_handler.send_sensor(
            sys_id, status_field, "Scanning...", sys_name, sys_model, 
            is_rtl=True, friendly_name=status_friendly_name
        )
        time.sleep(2)

        last_log_line = ""
        proc = None
        
        try:
            # stderr=subprocess.STDOUT merges error messages into the standard output stream
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

            for line in proc.stdout:
                if not line: continue
                safe_line = line.strip()

                # --- ERROR DETECTION ---
                if "usb_open error" in safe_line or "No supported devices" in safe_line or "No matching device" in safe_line:
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
                elif safe_line.startswith("{") and safe_line.endswith("}"):
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

                    # Utilities (Meter Reading Math)
                    if "Neptune-R900" in model and data.get("consumption") is not None:
                        real_val = float(data["consumption"]) / 10.0
                        data_processor.dispatch_reading(clean_id, "meter_reading", real_val, dev_name, model)
                        del data["consumption"]

                    if ("SCM" in model or "ERT" in model) and data.get("consumption") is not None:
                        data_processor.dispatch_reading(clean_id, "Consumption", data["consumption"], dev_name, model)
                        del data["consumption"]

                    # Dew Point Calculation
                    t_c = None
                    if "temperature_C" in data: t_c = data["temperature_C"]
                    elif "temp_C" in data: t_c = data["temp_C"]
                    elif "temperature_F" in data: t_c = (data["temperature_F"] - 32.0) * 5.0 / 9.0
                    elif "temperature" in data: t_c = data["temperature"]

                    if t_c is not None and data.get("humidity") is not None:
                        dp_f = calculate_dew_point(t_c, data["humidity"])
                        if dp_f is not None:
                            data_processor.dispatch_reading(clean_id, "dew_point", dp_f, dev_name, model)

                    # Flatten & Send
                    flat = flatten(data)
                    for key, value in flat.items():
                        if key in getattr(config, 'SKIP_KEYS', []): continue
                        
                        # Unit Conversions
                        if key in ["temperature_C", "temp_C"] and isinstance(value, (int, float)):
                            val_f = round(value * 1.8 + 32.0, 1)
                            data_processor.dispatch_reading(clean_id, "temperature", val_f, dev_name, model)
                        elif key in ["temperature_F", "temp_F", "temperature"] and isinstance(value, (int, float)):
                            data_processor.dispatch_reading(clean_id, "temperature", value, dev_name, model)
                        else:
                            data_processor.dispatch_reading(clean_id, key, value, dev_name, model)
                
                # --- CATCH ALL: LOG OUTPUT ---
                else:
                    if safe_line:
                        last_log_line = safe_line
                        print(f"[{radio_name} LOG] {safe_line}")

            if proc: proc.wait()
            if proc.returncode != 0:
                error_msg = f"Crashed: {last_log_line}" if last_log_line else f"Crashed Code {proc.returncode}"
                print(f"[{radio_name}] Process exited with code {proc.returncode}")
                mqtt_handler.send_sensor(
                    sys_id, status_field, error_msg[:255], sys_name, sys_model, 
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