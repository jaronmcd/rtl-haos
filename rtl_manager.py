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

def rtl_loop(radio_config: dict, mqtt_handler, data_processor, sys_id: str, sys_model: str) -> None:
    device_id = radio_config.get("id")
    if device_id: device_id = str(device_id).strip()

    device_index = radio_config.get("index")
    naming_id = device_id if device_id else "0"

    radio_name = radio_config.get("name")
    if not radio_name:
        radio_name = f"RTL_{naming_id}"
    
    # Defaults
    sample_rate = radio_config.get("rate") or "250k"
    raw_freq = radio_config.get("freq") or "433.92M"
    hop_interval = radio_config.get("hop_interval")
    
    frequencies = []
    if isinstance(raw_freq, list):
        frequencies = [str(f) for f in raw_freq]
    else:
        frequencies = [f.strip() for f in str(raw_freq).split(",")]

    # Safety Check for Units
    for f in frequencies:
        if f.endswith("m"):
             print(f"[{radio_name}] WARNING: Frequency '{f}' uses lowercase 'm' (milli). Did you mean '{f.upper()}' (Mega)?")
        elif f.replace('.', '', 1).isdigit():
             try:
                 val = float(f)
                 if val < 24000000:
                     print(f"[{radio_name}] WARNING: Frequency '{f}' has no units! Did you mean '{f}M'?")
             except ValueError:
                 pass   

    status_field = f"radio_status_{naming_id}"
    status_friendly_name = f"{radio_name}"
    sys_name = f"{sys_model} ({sys_id})"

    cmd = ["rtl_433"]
    if device_index is not None:
        cmd.extend(["-d", str(device_index)])
        print(f"[{radio_name}] Selecting by Index: {device_index}")
    elif device_id:
        cmd.extend(["-d", f":{device_id}"])
        print(f"[{radio_name}] Selecting by Serial: {device_id}")

    for f in frequencies:
        cmd.extend(["-f", f])
    
    if len(frequencies) > 1 and hop_interval:
        cmd.extend(["-H", str(hop_interval)])

    cmd.extend([
        "-s", sample_rate,
        "-F", "json", "-F", "log", 
        "-M", "time:iso", "-M", "protocol", "-M", "level"
    ])

    print(f"[RTL] Manager started for {radio_name}. Freqs: {frequencies}")

    state = {
        "last_packet": time.time(),
        "current_display": "Scanning...",
        "last_mqtt_update": 0
    }

    # Watchdog
    def watchdog_loop():
        while True:
            time.sleep(10)
            time_since_last = time.time() - state["last_packet"]
            if time_since_last > 600 and state["current_display"] != "Scanning...":
                state["current_display"] = "Scanning..."
                mqtt_handler.send_sensor(
                    sys_id, status_field, "Scanning...", sys_name, sys_model, 
                    is_rtl=True, friendly_name=status_friendly_name
                )
                print(f"[{radio_name}] Status reverted to Scanning... (No signal for 10m)")

    threading.Thread(target=watchdog_loop, daemon=True).start()

    while True:
        state["current_display"] = "Scanning..."
        mqtt_handler.send_sensor(
            sys_id, status_field, "Scanning...", sys_name, sys_model, 
            is_rtl=True, friendly_name=status_friendly_name
        )
        time.sleep(2)

        last_log_line = ""
        proc = None
        
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            ACTIVE_PROCESSES.append(proc) 

            for line in proc.stdout:
                if not line: continue
                safe_line = line.strip()

                if "usb_open error" in safe_line or "No supported devices" in safe_line or "No matching device" in safe_line:
                    print(f"[{radio_name}] WARNING: Hardware missing! Device not found.")
                    state["current_display"] = "No Device"
                    mqtt_handler.send_sensor(sys_id, status_field, "No Device", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
                
                elif "Kernel driver is active" in safe_line or "LIBUSB_ERROR_BUSY" in safe_line:
                    print(f"[{radio_name}] WARNING: USB Busy/Driver Error!")
                    state["current_display"] = "USB Error"
                    mqtt_handler.send_sensor(sys_id, status_field, "USB Error", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)

                elif safe_line.startswith("{") and safe_line.endswith("}"):
                    now = time.time()
                    state["last_packet"] = now
                    
                    show_timestamps = getattr(config, "RTL_SHOW_TIMESTAMPS", False)

                    if show_timestamps:
                        if now - state["last_mqtt_update"] > 5:
                            state["last_mqtt_update"] = now
                            ts = datetime.now().strftime("%H:%M:%S")
                            display_str = f"Last: {ts}"
                            state["current_display"] = display_str
                            mqtt_handler.send_sensor(sys_id, status_field, display_str, sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
                    else:
                        if state["current_display"] != "Online":
                            state["current_display"] = "Online"
                            mqtt_handler.send_sensor(sys_id, status_field, "Online", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)

                    try:
                        data = json.loads(safe_line)
                    except:
                        continue

                    model = data.get("model", "Generic")
                    sid = data.get("id") or data.get("channel") or "unknown"
                    clean_id = clean_mac(sid)
                    dev_name = f"{model} ({clean_id})"
                    dev_type = data.get("type", "Untyped")

                    whitelist = getattr(config, "DEVICE_WHITELIST", [])
                    if whitelist:
                        is_allowed = False
                        for pattern in whitelist:
                            if fnmatch.fnmatch(str(clean_id), pattern) or fnmatch.fnmatch(model, pattern):
                                is_allowed = True
                                break
                        if not is_allowed: continue
                    else:
                        if is_blocked_device(clean_id, model, dev_type): continue

                    if getattr(config, "DEBUG_RAW_JSON", False):
                        print(f"[DEBUG] [{radio_name}] RX: {safe_line}")

                    # --- UPDATED: Pass radio_name to all dispatch calls ---
                    if "Neptune-R900" in model and data.get("consumption") is not None:
                        real_val = float(data["consumption"]) / 10.0
                        data_processor.dispatch_reading(clean_id, "meter_reading", real_val, dev_name, model, radio_name=radio_name)
                        del data["consumption"]

                    if ("SCM" in model or "ERT" in model) and data.get("consumption") is not None:
                        data_processor.dispatch_reading(clean_id, "Consumption", data["consumption"], dev_name, model, radio_name=radio_name)
                        del data["consumption"]

                    t_c = None
                    if "temperature_C" in data: t_c = data["temperature_C"]
                    elif "temp_C" in data: t_c = data["temp_C"]
                    elif "temperature_F" in data: t_c = (data["temperature_F"] - 32.0) * 5.0 / 9.0
                    elif "temperature" in data: t_c = data["temperature"]

                    if t_c is not None and data.get("humidity") is not None:
                        dp_f = calculate_dew_point(t_c, data["humidity"])
                        if dp_f is not None:
                            data_processor.dispatch_reading(clean_id, "dew_point", dp_f, dev_name, model, radio_name=radio_name)

                    flat = flatten(data)
                    for key, value in flat.items():
                        if key in getattr(config, 'SKIP_KEYS', []): continue
                        
                        if key in ["temperature_C", "temp_C"] and isinstance(value, (int, float)):
                            val_f = round(value * 1.8 + 32.0, 1)
                            data_processor.dispatch_reading(clean_id, "temperature", val_f, dev_name, model, radio_name=radio_name)
                        elif key in ["temperature_F", "temp_F", "temperature"] and isinstance(value, (int, float)):
                            data_processor.dispatch_reading(clean_id, "temperature", value, dev_name, model, radio_name=radio_name)
                        else:
                            data_processor.dispatch_reading(clean_id, key, value, dev_name, model, radio_name=radio_name)
                
                else:
                    if safe_line:
                        last_log_line = safe_line
                        print(f"[{radio_name} LOG] {safe_line}")

            if proc: proc.wait()
            if proc in ACTIVE_PROCESSES: ACTIVE_PROCESSES.remove(proc)

            if proc.returncode != 0 and proc.returncode != -15:
                state["current_display"] = "Crashed"
                error_msg = f"Crashed: {last_log_line}" if last_log_line else f"Crashed Code {proc.returncode}"
                print(f"[{radio_name}] WARNING: Process exited with code {proc.returncode}")
                mqtt_handler.send_sensor(sys_id, status_field, error_msg[:255], sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)

        except Exception as e:
            state["current_display"] = "Crashed"
            print(f"[{radio_name}] WARNING: Exception: {e}")
            mqtt_handler.send_sensor(sys_id, status_field, "Script Error", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)

        if proc and (proc.returncode == -15 or proc.returncode == 0):
            print(f"[{radio_name}] Fast restart triggered.")
            mqtt_handler.send_sensor(sys_id, status_field, "Rebooting...", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
            time.sleep(10)
        else:
            print(f"[{radio_name}] WARNING: Retrying in 30 seconds...")
            time.sleep(30)