#!/usr/bin/env python3
"""
FILE: rtl_mqtt_bridge.py
DESCRIPTION:
  The main executable script.
  - FINAL VER: Synched System Logs, Electric Blue Debug, Glitch-Free Dashboard.
"""
import re # <--- Add this with your other imports
import subprocess
import json
import time
import threading
import sys
import importlib.util
import fnmatch
import socket
import statistics 
from datetime import datetime
import version
from rich.live import Live
from collections import deque
from rich.console import Group
from rich import print
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.syntax import Syntax
from rich.text import Text

console = Console()

# --- PRE-FLIGHT DEPENDENCY CHECK ---
def check_dependencies():
    if not subprocess.run(["which", "rtl_433"], capture_output=True).stdout:
        print("CRITICAL: 'rtl_433' binary not found. Please install it.")
        sys.exit(1)
    if importlib.util.find_spec("paho") is None:
        print("CRITICAL: Python dependency 'paho-mqtt' not found.")
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

# ---------------- LOGGING HELPERS (THE MISSING PIECE) ----------------

def log_system_event(tag, message):
    """Prints a system log (THROTTLE, STARTUP, etc) with a Green Timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    console.print(f"[[green]{timestamp}[/green]] [bold green]{tag:<10}[/bold green] {message}")

def log_debug_packet(radio_name, raw_json_str):
    """
    Prints a raw JSON packet with 'Tron' styling using a Placeholder strategy.
    This prevents the regex from breaking the rich tags.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    s = raw_json_str
    
    # 1. HIDE structural punctuation (Replace with temporary placeholders)
    #    We do this so our styling tags don't get messed up later.
    s = s.replace('{', '§OB§').replace('}', '§CB§')
    s = s.replace('[', '§LB§').replace(']', '§RB§')
    s = s.replace(',', '§CM§')

    # 2. Format KEYS (White)
    #    Target: "key":
    #    We use [dim] tags here, but they are safe because we hid the real brackets above.
    s = re.sub(
        r'"([^"]+)"\s*:', 
        r'[dim]"[/dim][bold white]\1[/bold white][dim]":[/dim]', 
        s
    )
    
    # 3. Format VALUES (String) (Cyan)
    #    Target: [dim]":[/dim] "value"
    s = re.sub(
        r'(\[dim\]":\[/dim\]\s*)"([^"]+)"', 
        r'\1[dim]"[/dim][bold cyan]\2[/bold cyan][dim]"[/dim]', 
        s
    )
    
    # 4. Format VALUES (Number/Bool) (Cyan)
    #    Target: [dim]":[/dim] 123
    s = re.sub(
        r'(\[dim\]":\[/dim\]\s*)([0-9.-]+|true|false|null)', 
        r'\1[bold cyan]\2[/bold cyan]', 
        s
    )

    # 5. RESTORE structural punctuation (with Dim styling)
    #    Now we turn the placeholders back into real brackets.
    s = s.replace('§OB§', '[dim]{[/dim]').replace('§CB§', '[dim]}[/dim]')
    s = s.replace('§LB§', '[dim][[/dim]').replace('§RB§', '[dim]][/dim]')
    s = s.replace('§CM§', '[dim],[/dim]')

    # Print
    console.print(
        f"[dim]\[[/dim]{timestamp}[dim]][/dim] 🐛 [bold deep_sky_blue1]{radio_name:<25}[/bold deep_sky_blue1] "
        f"| [bold cyan]RAW[/bold cyan]                : "
        f"{s}"
    )

    
# ---------------- DASHBOARD ----------------
def get_dashboard_layout(sys_id, sys_model, frame=0):
    logo_lines = [
        r"██████╗ ████████╗██╗     ______ ██╗  ██╗ █████╗  ██████╗ ███████╗",
        r"██╔══██╗╚══██╔══╝██║     ██████╗██║  ██║██╔══██╗██╔═══██╗██╔════╝",
        r"██████╔╝   ██║   ██║     ╚═════╝███████║███████║██║   ██║███████╗",
        r"██╔══██╗   ██║   ██║            ██╔══██║██╔══██║██║   ██║╚════██║",
        r"██║  ██║   ██║   ███████╗       ██║  ██║██║  ██║╚██████╔╝███████║",
        r"╚═╝  ╚═╝   ╚═╝   ╚══════╝       ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
    ]
    base_colors = ["#FF00FF", "#E011FF", "#C222FF", "#A333FF", "#8544FF", "#0088FF"]
    
    dq = deque(base_colors)
    dq.rotate(frame) 
    current_colors = list(dq)

    gradient_logo = Text()
    for line, color in zip(logo_lines, current_colors):
        gradient_logo.append(line + "\n", style=color)

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold blue", expand=True)
    table.add_column("Category", style="cyan", width=12)
    table.add_column("Setting", style="dim white", width=20)
    table.add_column("Value", style="bold white")

    table.add_row("SYSTEM", "Device Model", sys_model)
    table.add_row("", "System ID", sys_id)
    table.add_row("MQTT", "Broker", f"{config.MQTT_SETTINGS['host']}")
    table.add_section()
    
    radios = getattr(config, "RTL_CONFIG", [])
    r_stat = f"[green]{len(radios)} Active[/green]" if radios else "[cyan]Auto-Detect[/cyan]"
    table.add_row("RADIO", "Mode", r_stat)
    
    purge = getattr(config, "DEVICE_PURGE_INTERVAL", 0)
    p_str = f"{purge/3600:.1f} Hours" if purge >= 3600 else (f"{purge}s" if purge > 0 else "[red]Disabled[/red]")
    table.add_row("LOGIC", "Auto-Remove", p_str)

    scan_status = "[bold yellow] SCANNING [/bold yellow]" if frame % 10 < 5 else "[dim yellow] SCANNING [/dim yellow]"
    
    return Panel(
        Group(gradient_logo, table),
        border_style="bold blue",
        title="[bold blue] SYSTEM ONLINE [/bold blue]",
        subtitle=f"[bold white]v{version.__version__}[/bold white] • {scan_status}",
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

    # UPDATED: Use log_system_event
    log_system_event("[THROTTLE]", f"Averaging data every {interval} seconds.")
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
            # UPDATED: Use log_system_event
            log_system_event("[THROTTLE]", f"Flushed {count_sent} averaged readings.")

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

def rtl_loop(radio_config, mqtt_handler, sys_id, sys_model, signal_event):
    device_id = radio_config.get("id", "0")
    frequency = radio_config.get("freq", "433.92M")
    radio_name = radio_config.get("name", f"RTL_{device_id}")
    sample_rate = radio_config.get("rate", "250k")

    status_field = f"radio_status_{device_id}"
    status_friendly_name = f"{radio_name}"
    sys_name = f"{sys_model} ({sys_id})"

    cmd = ["rtl_433", "-d", f":{device_id}", "-f", frequency, "-s", sample_rate, "-F", "json", "-M", "time:iso", "-M", "protocol", "-M", "level"]

    # UPDATED: Use log_system_event
    log_system_event("[RTL]", f"Manager started for {radio_name}. Monitoring...")

    while True:
        mqtt_handler.send_sensor(sys_id, status_field, "Scanning...", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
        time.sleep(2)

        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in proc.stdout:
                if not line: continue
                safe_line = line.strip()

                if "usb_open error" in safe_line or "No supported devices" in safe_line:
                    log_system_event("[ERROR]", f"[{radio_name}] Hardware missing!")
                    mqtt_handler.send_sensor(sys_id, status_field, "No Device Found", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
                
                if safe_line.startswith("{") and safe_line.endswith("}"):
                    try:
                        data = json.loads(safe_line)
                        
                        if not signal_event.is_set():
                            signal_event.set()
                            time.sleep(3.0) # Morph wait

                        mqtt_handler.send_sensor(sys_id, status_field, "Online", sys_name, sys_model, is_rtl=True, friendly_name=status_friendly_name)
                    except:
                        continue

                    model = data.get("model", "Generic")
                    sid = data.get("id") or data.get("channel") or "unknown"
                    clean_id = clean_mac(sid)
                    dev_name = f"{model} ({clean_id})"

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
                        log_debug_packet(radio_name, safe_line)

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

            if proc: proc.wait()
        except Exception as e:
            print(f"[{radio_name}] Exception: {e}")
        time.sleep(30)

def purge_loop(mqtt_handler):
    # UPDATED: Use log_system_event
    log_system_event("[STARTUP]", "Auto-Remove / Purge Loop started.")
    while True:
        time.sleep(60)
        try:
            mqtt_handler.prune_stale_devices()
        except Exception as e:
            log_system_event("[ERROR]", f"Purge loop failed: {e}")

def main():
    # --- 1. SETUP & IDENTITY ---
    mqtt_handler = HomeNodeMQTT()
    sys_id = get_system_mac().replace(":", "").lower()
    sys_model = socket.gethostname().title()
    first_signal_event = threading.Event()

    # --- 2. START ALL THREADS ---
    mqtt_handler.start()

    rtl_config = getattr(config, "RTL_CONFIG", None)
    if rtl_config:
        for radio in rtl_config:
            threading.Thread(target=rtl_loop, args=(radio, mqtt_handler, sys_id, sys_model, first_signal_event), daemon=True).start()
    else:
        auto_serial = discover_default_rtl_serial()
        auto_radio = {"name": f"RTL_{auto_serial}", "id": auto_serial} if auto_serial else {"name": "RTL_auto", "id": "0"}
        threading.Thread(target=rtl_loop, args=(auto_radio, mqtt_handler, sys_id, sys_model, first_signal_event), daemon=True).start()

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
            while not first_signal_event.is_set():
                live.update(get_dashboard_layout(sys_id, sys_model, frame_counter))
                frame_counter += 1
                time.sleep(0.1) 

            # Phase 2: Signal Locked
            final_panel = get_dashboard_layout(sys_id, sys_model, 0)
            final_panel.border_style = "bold green"
            final_panel.title = "[bold green] SYSTEM ONLINE [/bold green]"
            final_panel.subtitle = "[bold green]✔ SIGNAL LOCKED [/bold green]"
            live.update(final_panel)
            time.sleep(1.5)
            
    except KeyboardInterrupt:
        console.print("\n[bold red][SHUTDOWN] Stopping MQTT...[/bold red]")
        mqtt_handler.stop()
        sys.exit(0)

    # --- 5. CLEAN SLATE ---
    console.clear()

    # --- 6. LOG STREAM STARTING ---
    console.print("[bold green]✔ Data Stream Active[/bold green]")
    
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[bold red][SHUTDOWN] Stopping MQTT...[/bold red]")
        mqtt_handler.stop()
        sys.exit(0)

if __name__ == "__main__":
    main()