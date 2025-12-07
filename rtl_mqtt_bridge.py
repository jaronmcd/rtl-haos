#!/usr/bin/env python3
import subprocess
import json
import time
import threading
import sys
import importlib.util
import fnmatch
import socket
import statistics 
import shlex 
from datetime import datetime
from collections import deque
import re

# --- RICH UI IMPORTS ---
from rich.live import Live
from rich.console import Group
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.text import Text

# --- LOCAL IMPORTS ---
import config
from utils import clean_mac, calculate_dew_point, get_system_mac
from mqtt_handler import HomeNodeMQTT
from field_meta import FIELD_META 
from system_monitor import system_stats_loop
import version

# --- LOGGER IMPORT ---
import logger
from logger import console

# --- SHARED STATE ---
RUNTIME_VARS = {
    "current_freq": "INITIALIZING",
    "status_msg": "STARTING UP"
}

# --- PRE-FLIGHT DEPENDENCY CHECK ---
def check_dependencies():
    if importlib.util.find_spec("paho") is None:
        logger.error("CRITICAL", "Python dependency 'paho-mqtt' not found.")
        sys.exit(1)

check_dependencies()

# --- BUFFER GLOBALS ---
DATA_BUFFER = {} 
BUFFER_LOCK = threading.Lock()

# ---------------- DASHBOARD ----------------
def get_dashboard_layout(sys_id, sys_model, frame=0, is_locked=False):
    # --- 1. THEME SELECTION ---
    if is_locked:
        base_color = "green"
        accent_color = "bold green"
        border_style = "green"
        logo_color_list = ["#00FF00"] * 6  
        status_msg = "[bold green]✔ SIGNAL LOCKED[/bold green]"
        box_type = box.HEAVY 
        scanner_active = False
    else:
        base_color = "cyan"
        accent_color = "bold cyan"
        border_style = "cyan" 
        logo_color_list = ["#E0FFFF", "#00FFFF", "#00D5FF", "#00AAFF", "#0077FF", "#0044FF"] 
        
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        spin_char = spinner_chars[frame % len(spinner_chars)]
        
        freq = RUNTIME_VARS.get("current_freq", "WAITING")
        status_msg = f"[{base_color}]{spin_char} SCANNING {freq}...[/{base_color}]"
        
        box_type = box.ROUNDED
        scanner_active = True

    # --- 2. LOGO GENERATION ---
    logo_lines = [
        r"██████╗ ████████╗██╗     ______ ██╗  ██╗ █████╗  ██████╗ ███████╗",
        r"██╔══██╗╚══██╔══╝██║     ██████╗██║  ██║██╔══██╗██╔═══██╗██╔════╝",
        r"██████╔╝   ██║   ██║     ╚═════╝███████║███████║██║   ██║███████╗",
        r"██╔══██╗   ██║   ██║            ██╔══██║██╔══██║██║   ██║╚════██║",
        r"██║  ██║   ██║   ███████╗       ██║  ██║██║  ██║╚██████╔╝███████║",
        r"╚═╝  ╚═╝   ╚═╝   ╚══════╝       ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
    ]
    
    dq = deque(logo_color_list)
    dq.rotate(frame if not is_locked else 0) 
    current_colors = list(dq)

    gradient_logo = Text()
    for line, color in zip(logo_lines, current_colors):
        gradient_logo.append(line + "\n", style=color)

    # --- 3. SYSTEM TABLE ---
    table = Table(box=box.HORIZONTALS, show_header=False, expand=True, padding=(1, 1))
    table.add_column("COMPONENT", style=f"bold {base_color}", justify="left", ratio=1)
    table.add_column("STATUS", style="bold white", justify="right", ratio=2)
    
    # -- Data Prep --
    radios = getattr(config, "RTL_CONFIG", [])
    r_count = f"{len(radios)}" if radios else "AUTO"
    
    # Check TCP Config
    tcp_enabled = getattr(config, "TCP_LISTEN_ENABLED", False)
    tcp_port = getattr(config, "TCP_LISTEN_PORT", 4000)
    
    if tcp_enabled:
        tcp_stat = f"[bold green]OPEN (PORT {tcp_port})[/bold green]"
    else:
        tcp_stat = "[dim]DISABLED[/dim]"

    # -- Rows --
    table.add_row("CORE SYSTEM", f"{sys_model}\n[dim]{sys_id}[/dim]")
    table.add_row("MQTT BRIDGE", f"{config.MQTT_SETTINGS['host']}")
    table.add_row("RTL RADIO", f"ACTIVE NODES: {r_count}")
    table.add_row("TCP INPUT", tcp_stat) 
    
    # --- 4. SCANNER ANIMATION ---
    if scanner_active:
        width = 40
        cycle = (width - 1) * 2
        pos = frame % cycle
        if pos >= width: pos = cycle - pos
            
        track_chars = ["·"] * width
        if 0 <= pos < width: track_chars[pos] = "█"     
        if 0 <= pos-1 < width: track_chars[pos-1] = "▓" 
        if 0 <= pos+1 < width: track_chars[pos+1] = "▓" 
        if 0 <= pos-2 < width: track_chars[pos-2] = "▒" 
        if 0 <= pos+2 < width: track_chars[pos+2] = "▒" 
            
        scanner_str = "".join(track_chars)
        
        visualizer = Panel(
            Text(scanner_str, style=f"bold {base_color}", justify="center"),
            title="[dim]ACTIVE SEARCH[/dim]", 
            title_align="center",
            border_style=f"dim {base_color}",
            box=box.HORIZONTALS,
            padding=(0,0)
        )
    else:
        visualizer = Panel(
            Text("▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬", style="bold green", justify="center"),
            title="[bold green]LINK ESTABLISHED[/bold green]", 
            title_align="center",
            border_style="green",
            box=box.HORIZONTALS,
            padding=(0,0)
        )

    # --- 5. FOOTER ---
    mem_usage = 12 + (frame % 5)
    footer_text = Text.from_markup(
        f"[dim]CPU:[/dim] [bold {base_color}]OK[/]    "
        f"[dim]MEM:[/dim] [bold {base_color}]{mem_usage}%[/]    "
        f"[dim]ENC:[/dim] [bold {base_color}]OFF[/]    "
        f"[dim]PWR:[/dim] [bold {base_color}]STABLE[/]",
        justify="center"
    )

    # --- 6. ASSEMBLE ---
    return Panel(
        Group(
            gradient_logo, 
            Text(" "), 
            table, 
            Text(" "), 
            visualizer,
            Text(" "), 
            footer_text
        ),
        border_style=border_style,
        box=box_type,
        title=f"[{accent_color}] ❖ BRIDGE PROTOCOL ❖ [/{accent_color}]",
        subtitle=status_msg,
    )

# ---------------- LOGIC ----------------

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

    logger.info("[THROTTLE]", f"Averaging data every {interval} seconds.")
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
            logger.info("[THROTTLE]", f"Flushed {count_sent} averaged readings.")

# --- SHARED PACKET PROCESSING (USB & TCP) ---
def process_packet(raw_line, source_name, mqtt_handler, signal_event=None):
    """
    Core logic: Decodes JSON, checks whitelist/blacklist, calculates extras, dispatches.
    """
    safe_line = raw_line.strip()
    if not safe_line.startswith("{") or not safe_line.endswith("}"):
        return

    try:
        data = json.loads(safe_line)
        
        # Unlock dashboard on first successful packet
        if signal_event and not signal_event.is_set():
            signal_event.set()
            time.sleep(1.0) 

    except:
        return

    model = data.get("model", "Generic")
    sid = data.get("id") or data.get("channel") or "unknown"
    clean_id = clean_mac(sid)
    dev_name = f"{model} ({clean_id})"

    # Whitelist / Blacklist
    whitelist = getattr(config, "DEVICE_WHITELIST", [])
    if whitelist:
        is_allowed = False
        for pattern in whitelist:
            if fnmatch.fnmatch(str(clean_id), pattern) or fnmatch.fnmatch(model, pattern):
                is_allowed = True
                break
        if not is_allowed: return
    else:
        if is_blocked_device(clean_id, model): return

    # Debug Raw
    if getattr(config, "DEBUG_RAW_JSON", False):
        logger.raw_json(source_name, safe_line)

    # Utilities & Sensor Logic
    if "Neptune-R900" in model and data.get("consumption") is not None:
        real_val = float(data["consumption"]) / 10.0
        dispatch_reading(clean_id, "meter_reading", real_val, dev_name, model, mqtt_handler)
        del data["consumption"]

    if ("SCM" in model or "ERT" in model) and data.get("consumption") is not None:
        dispatch_reading(clean_id, "Consumption", data["consumption"], dev_name, model, mqtt_handler)
        del data["consumption"]

    t_c = None
    if "temperature_C" in data: t_c = data["temperature_C"]
    elif "temp_C" in data: t_c = data["temp_C"]
    elif "temperature_F" in data: t_c = (data["temperature_F"] - 32.0) * 5.0 / 9.0
    elif "temperature" in data: t_c = data["temperature"]

    if t_c is not None and data.get("humidity") is not None:
        dp_f = calculate_dew_point(t_c, data["humidity"])
        if dp_f is not None:
            dispatch_reading(clean_id, "dew_point", dp_f, dev_name, model, mqtt_handler)

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


def discover_default_rtl_serial():
    try:
        proc = subprocess.run(["rtl_eeprom"], capture_output=True, text=True, timeout=10)
    except:
        return None
    output = (proc.stdout or "") + (proc.stderr or "")
    for line in output.splitlines():
        if "Serial number" in line or "S/N" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip().split()[0]
    return None

def validate_radio_device(device_id=None, rtl_path="rtl_433"):
    """
    Checks if the specified SDR device exists. 
    If device_id is None, it checks if ANY radio is available.
    """
    # --- CONFIGURATION CHECK ---
    if device_id is None:
        all_radios = getattr(config, "RTL_CONFIG", [])
        
        # If we have multiple radios defined in config...
        if all_radios and len(all_radios) > 1:
            # ...fail if EVEN ONE is missing an ID.
            # Mixed mode (some with ID, some without) causes race conditions.
            if any(r.get("id") is None for r in all_radios):
                raise ValueError(
                    "Configuration Error: Ambiguous Radio Setup. "
                    "When using multiple radios, EVERY radio must have a unique 'id' "
                    "to prevent them from fighting over the same USB hardware."
                )

    msg = f"ID {device_id}" if device_id else "First Available (Auto)"
    logger.info("[HARDWARE]", f"Testing connectivity for Radio: {msg} using '{rtl_path}'...")
    
    # Base command: Run for 1 second (-T 1)
    cmd = [rtl_path, "-T", "1"]
    
    # Only add the Device Flag if the user specifically asked for an ID
    if device_id:
        cmd.extend(["-d", f":{device_id}"])
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            full_output = (result.stderr + result.stdout).strip()
            
            if "No supported device" in full_output:
                 raise ValueError(f"Radio ({msg}) not found. Is it plugged in?")
            elif "usb_claim_interface" in full_output or "Device or resource busy" in full_output:
                 raise PermissionError(f"Radio ({msg}) is BUSY. (Is another instance of rtl_433 running?)")
            else:
                raise RuntimeError(f"Radio Self-Test Failed.\nOutput:\n{full_output}")

        logger.info("[HARDWARE]", "✔ Radio checks out. Hardware is responding.")
        return True

    except FileNotFoundError:
        logger.error("CRITICAL", f"'{rtl_path}' command not found. Please install it or check 'rtl_433_cmd' in config.")
        sys.exit(1)
    except Exception as e:
        raise e

def rtl_loop(radio_config, mqtt_handler, sys_id, sys_model, signal_event):
    # 1. Config & Defaults
    device_id = radio_config.get("id") 
    display_id = device_id if device_id else "0"
    
    # Allow custom binary path (default to standard command)
    rtl_binary = radio_config.get("rtl_433_cmd", "rtl_433")
    
    radio_name = radio_config.get("name", f"RTL_{display_id}")
    sample_rate = radio_config.get("rate", "250k")
    
    raw_freq = radio_config.get("freq", "433.92M")
    hop_interval = radio_config.get("hop_interval", 60)
    
    # Dashboard: Show FULL plan, not trying to update live
    freq_list = raw_freq if isinstance(raw_freq, list) else [raw_freq]
    scan_display = ", ".join(str(f).replace("M", "M").replace("k", "k") for f in freq_list)
    RUNTIME_VARS["current_freq"] = f"{scan_display}"

    # Define Sensor IDs 
    status_field = f"radio_status_{display_id}"
    plan_field = f"scan_plan_{display_id}"
    
    status_friendly_name = f"{radio_name}"
    sys_name = f"{sys_model} ({sys_id})"

    # --- COMMAND CONSTRUCTION ---
    # Start with binary and sample rate
    cmd = [rtl_binary, "-s", sample_rate]

    if device_id:
        cmd.extend(["-d", f":{device_id}"])

    # --- INJECT RAW PARAMS (Custom Flags) ---
    raw_params = radio_config.get("raw_params")
    if raw_params:
        if isinstance(raw_params, list):
            cmd.extend(raw_params)
        elif isinstance(raw_params, str):
            cmd.extend(shlex.split(raw_params))
    
    # Add Frequencies & Hopping
    if isinstance(raw_freq, list):
        for f in raw_freq:
            cmd.extend(["-f", str(f)])
        if len(raw_freq) > 1:
            cmd.extend(["-H", str(hop_interval)])
    else:
        cmd.extend(["-f", str(raw_freq)])

    cmd.extend(["-F", "json", "-M", "time:iso", "-M", "protocol", "-M", "level"])

    logger.info("[RTL]", f"Manager started for {radio_name}. Plan: {scan_display}")

    # --- MAIN MONITORING LOOP ---
    
    while True:
        # Publish Status
        mqtt_handler.send_sensor(sys_id, status_field, "Scanning...", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
        time.sleep(2)

        proc = None
        try:
            # bufsize=1 and universal_newlines=True ensures real-time output
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            
            for line in proc.stdout:
                if not line: continue
                safe_line = line.strip()

                if "usb_open error" in safe_line or "No supported devices" in safe_line:
                    logger.error("[ERROR]", f"[{radio_name}] Hardware missing!")
                    mqtt_handler.send_sensor(sys_id, status_field, "No Device Found", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
                
                # --- PROCESS JSON DATA ---
                if safe_line.startswith("{") and safe_line.endswith("}"):
                    mqtt_handler.send_sensor(sys_id, status_field, "Online", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
                    
                    # Hand off to shared processor
                    process_packet(safe_line, radio_name, mqtt_handler, signal_event)

            if proc: proc.wait()
        except Exception as e:
            logger.error(radio_name, f"Exception: {e}")
        time.sleep(30)

def tcp_bridge_loop(mqtt_handler, signal_event):
    """
    Listens for JSON data from other machines (e.g. 'rtl_433 -F json:HOST:PORT').
    """
    port = getattr(config, "TCP_LISTEN_PORT", 4000)
    logger.info("[TCP]", f"Listening for remote JSON on port {port}...")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allow port reuse if script restarts quickly
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind(('0.0.0.0', port))
        server.listen(5)
    except Exception as e:
        logger.error("[TCP]", f"Failed to bind port {port}: {e}")
        return

    while True:
        try:
            client, addr = server.accept()
            logger.info("[TCP]", f"Connection from {addr[0]}")
            
            # Spin off a thread to handle this specific client so the server remains responsive
            threading.Thread(target=_handle_tcp_client, args=(client, addr, mqtt_handler, signal_event), daemon=True).start()
        except Exception as e:
            logger.error("[TCP]", f"Accept Error: {e}")

def _handle_tcp_client(client_socket, addr, mqtt_handler, signal_event):
    source_name = f"TCP_{addr[0]}"
    try:
        # 'makefile' allows us to read line-by-line easily
        with client_socket.makefile('r', encoding='utf-8', errors='ignore') as stream:
            for line in stream:
                if not line: break
                process_packet(line, source_name, mqtt_handler, signal_event)
    except Exception as e:
        logger.error(source_name, f"Disconnected: {e}")
    finally:
        client_socket.close()


def purge_loop(mqtt_handler):
    logger.info("[STARTUP]", "Auto-Remove / Purge Loop started.")
    while True:
        time.sleep(60)
        try:
            mqtt_handler.prune_stale_devices()
        except Exception as e:
            logger.error("[ERROR]", f"Purge loop failed: {e}")

def main():
    # --- 1. SETUP & IDENTITY ---
    print("Checking Hardware...")
    rtl_config = getattr(config, "RTL_CONFIG", None)
    if rtl_config:
        for radio in rtl_config:
            # Get ID (optional)
            r_id = radio.get("id") 
            # Get Custom Binary Path (optional)
            custom_bin = radio.get("rtl_433_cmd", "rtl_433")
            try:
                validate_radio_device(r_id, rtl_path=custom_bin)
            except Exception as e:
                print(f"\n[!!!] CRITICAL HARDWARE FAILURE: {e}")
                print("[!!!] The script will exit now.\n")
                sys.exit(1)

    logger.set_logging(False) 
    mqtt_handler = HomeNodeMQTT()
    sys_id = get_system_mac().replace(":", "").lower()
    sys_model = socket.gethostname().title()
    first_signal_event = threading.Event()

    # --- 2. START ALL THREADS ---
    mqtt_handler.start()
    
    if rtl_config:
        for radio in rtl_config:
            threading.Thread(target=rtl_loop, args=(radio, mqtt_handler, sys_id, sys_model, first_signal_event), daemon=True).start()
    else:
        # If no config, try auto-detect (USB)
        auto_serial = discover_default_rtl_serial()
        auto_radio = {"name": f"RTL_{auto_serial}", "id": auto_serial} if auto_serial else {"name": "RTL_auto", "id": "0"}
        
        # Only start USB listener if we actually found one OR if user didn't explicitly ask for TCP only.
        threading.Thread(target=rtl_loop, args=(auto_radio, mqtt_handler, sys_id, sys_model, first_signal_event), daemon=True).start()

    # START TCP LISTENER
    if getattr(config, "TCP_LISTEN_ENABLED", False):
        threading.Thread(target=tcp_bridge_loop, args=(mqtt_handler, first_signal_event), daemon=True).start()

    threading.Thread(target=system_stats_loop, args=(mqtt_handler, sys_id, sys_model), daemon=True).start()
    threading.Thread(target=throttle_flush_loop, args=(mqtt_handler,), daemon=True).start()
    if getattr(config, "DEVICE_PURGE_INTERVAL", 0) > 0:
        threading.Thread(target=purge_loop, args=(mqtt_handler,), daemon=True).start()


    # --- 3. SETTLE DOWN PHASE ---
    time.sleep(2.0)
    console.clear() 

    # --- 4. MORPH ANIMATION LOOP ---
    try:
        with Live(console=console, refresh_per_second=10, transient=False) as live:
            frame_counter = 0
            
            # PHASE A: SCANNING (Blue Tron Theme)
            while not first_signal_event.is_set():
                live.update(get_dashboard_layout(sys_id, sys_model, frame=frame_counter, is_locked=False))
                frame_counter += 1
                time.sleep(0.1) 

            # PHASE B: LOCKED (Green Matrix Theme)
            # We call the same function but set is_locked=True. 
            # This triggers the green gradient logo and borders defined in the previous step.
            final_panel = get_dashboard_layout(sys_id, sys_model, frame=frame_counter, is_locked=True)
            live.update(final_panel)
            
            # Hold the green "Success" screen for 1.5s
            time.sleep(1.5)
            
    except KeyboardInterrupt:
        logger.set_logging(True) 
        logger.warn("[SHUTDOWN]", "Stopping MQTT...")
        mqtt_handler.stop()
        sys.exit(0)

    # --- 5. CLEAN SLATE ---
    console.clear()
    
    # --- 6. UN-MUTE EVERYTHING ---
    logger.set_logging(True) 

    console.print("[bold green]✔ Data Stream Active[/bold green]")
    
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logger.warn("[SHUTDOWN]", "Stopping MQTT...")
        mqtt_handler.stop()
        sys.exit(0)

if __name__ == "__main__":
    main()