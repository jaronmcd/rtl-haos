#!/usr/bin/env python3
"""
FILE: main.py
DESCRIPTION:
  The main executable script.
  - UPDATED: Added explicit Warnings when NO hardware is detected on the USB bus.
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
    if "unsupported" in clean: return c_yellow
    if "supported" in clean: return c_green
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

def highlight_support_tags(text: str) -> str:
    # Normalize common variants (so old logs still color nicely)
    text = re.sub(r"\[\s*!!\s*UNSUPPORTED\s*!!\s*\]", "[UNSUPPORTED]", text)
    text = re.sub(r"\[\s*SUPPORTED\s*\]", "[SUPPORTED]", text)

    # Colorize tags anywhere in the line
    text = re.sub(
        r"\[UNSUPPORTED\]",
        f"{c_white}[{c_reset}{c_yellow}UNSUPPORTED{c_reset}{c_white}]{c_reset}",
        text,
    )
    text = re.sub(
        r"\[SUPPORTED\]",
        f"{c_white}[{c_reset}{c_green}SUPPORTED{c_reset}{c_white}]{c_reset}",
        text,
    )
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

        msg = highlight_support_tags(msg)
    _original_print(f"{time_prefix} {header} {msg}", flush=True, **kwargs)

builtins.print = timestamped_print

def check_dependencies():
    if not subprocess.run(["which", "rtl_433"], capture_output=True).stdout:
        print("CRITICAL: 'rtl_433' binary not found. Please install it.")
        sys.exit(1)
    if importlib.util.find_spec("paho") is None:
        print("CRITICAL: Python dependency 'paho-mqtt' not found.")
        sys.exit(1)



import config
from mqtt_handler import HomeNodeMQTT
from utils import (
    get_system_mac,
    validate_radio_config,
    get_homeassistant_country_code,
    choose_secondary_band_defaults,
    choose_hopper_band_defaults,
)
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
                        ver = line.split(':', 1)[1].strip()
                        ver = ver.strip().strip('\"').strip("'")
                        return f"v{ver}"
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
    check_dependencies()
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
    
    # --- Check for Physical Duplicates (Hardware) ---
    serial_counts = {}
    if detected_devices:
        for d in detected_devices:
            sid = str(d.get('id', ''))
            serial_counts[sid] = serial_counts.get(sid, 0) + 1
            if 'id' in d and 'index' in d: pass 

        for sid, count in serial_counts.items():
            if count > 1:
                print(f"[STARTUP] WARNING: [Hardware] Multiple SDRs detected with same Serial '{sid}'. IDs must be unique for precise mapping. Use rtl_eeprom to fix.")

    serial_to_index = {}
    if detected_devices:
        for d in detected_devices:
            if 'id' in d and 'index' in d:
                serial_to_index[str(d['id'])] = d['index']
        print(f"[STARTUP] Hardware Map: {serial_to_index}")
    else:
        # --- NEW WARNING: No Hardware Found ---
        print("[STARTUP] WARNING: [Hardware] No RTL-SDR devices found on USB bus. Ensure device is plugged in and passed through to VM/Container.")
        # --------------------------------------

    rtl_config = getattr(config, "RTL_CONFIG", None)

    if rtl_config:
        # --- A. MANUAL CONFIGURATION MODE ---
        print(f"[STARTUP] Loading {len(rtl_config)} radios from manual config.")
        configured_ids = set()
        seen_config_ids = set()

        for slot, radio in enumerate(rtl_config):
            radio.setdefault("slot", slot)  # fallback when 'id' is missing

            r_name = radio.get("name", "Unknown")
            
            warns = validate_radio_config(radio)
            for w in warns:
                print(f"[STARTUP] CONFIG WARNING: [Radio: {r_name}] {w}")

            target_id = radio.get("id") 
            if target_id: target_id = str(target_id).strip()
            
            if target_id and target_id in seen_config_ids:
                print(f"[STARTUP] CONFIG ERROR: [Radio: {r_name}] Duplicate ID '{target_id}' found in settings. Skipping this radio to prevent conflicts.")
                continue 
            
            if target_id:
                seen_config_ids.add(target_id)
            
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
                    print(f"[STARTUP] WARNING: [Radio: Serial {d_id}] Detected but NOT configured. It is currently idle.")
            
    else:
        # --- B. SMART AUTO-CONFIGURATION MODE ---
        if detected_devices:
            print(f"[STARTUP] Auto-detected {len(detected_devices)} radios.")

            # Auto Multi-Radio: if a 2nd dongle is present, start a second rtl_433 instance automatically.
            if getattr(config, "RTL_AUTO_MULTI", False) and len(detected_devices) > 1:
                max_radios_cfg = getattr(config, "RTL_AUTO_MAX_RADIOS", 0)
                try:
                    max_radios_cfg = int(max_radios_cfg)
                except Exception:
                    max_radios_cfg = 0

                # rtl_auto_max_radios:
                #   0 -> use detected count (bounded by RTL_AUTO_HARD_CAP)
                #  >0 -> start that many (bounded by available dongles)
                if max_radios_cfg <= 0:
                    hard_cap = getattr(config, "RTL_AUTO_HARD_CAP", 3)
                    try:
                        hard_cap = int(hard_cap)
                    except Exception:
                        hard_cap = 3
                    if hard_cap < 1:
                        hard_cap = 1
                    max_radios = min(len(detected_devices), hard_cap)
                else:
                    max_radios = min(max_radios_cfg, len(detected_devices))

                if max_radios_cfg <= 0:
                    try:
                        hard_cap_disp = int(getattr(config, "RTL_AUTO_HARD_CAP", 3) or 3)
                    except Exception:
                        hard_cap_disp = 3
                    print(
                        f"[STARTUP]: Auto Multi-Radio: rtl_auto_max_radios=0 -> starting {max_radios} radio(s) (cap={hard_cap_disp})."
                    )
                else:
                    print(
                        f"[STARTUP]: Auto Multi-Radio: rtl_auto_max_radios={max_radios_cfg} -> starting {max_radios} radio(s)."
                    )


                country = get_homeassistant_country_code()
                plan = getattr(config, "RTL_AUTO_BAND_PLAN", "auto")
                sec_override = str(getattr(config, "RTL_AUTO_SECONDARY_FREQ", "") or "").strip()
                sec_freq, sec_hop = choose_secondary_band_defaults(
                    plan=plan,
                    country_code=country,
                    secondary_override=sec_override,
                )

                # PRIMARY uses RTL_DEFAULT_FREQ; SECONDARY uses region-aware defaults.
                print("[STARTUP] Unconfigured Mode: Auto Multi-Radio enabled.")
                if country:
                    print(f"[STARTUP] Auto Multi-Radio: HA country={country}, band_plan={plan} -> secondary={sec_freq}")
                else:
                    print(f"[STARTUP] Auto Multi-Radio: HA country=unknown, band_plan={plan} -> secondary={sec_freq}")

                radios = []

                # --- Radio #1 (Primary) ---
                dev1 = detected_devices[0]
                name1 = dev1.get("name", "Primary")

                def_freqs = str(config.RTL_DEFAULT_FREQ).split(",")
                def_hop = int(getattr(config, "RTL_DEFAULT_HOP_INTERVAL", 0) or 0)
                if len(def_freqs) < 2:
                    def_hop = 0
                elif def_hop <= 0:
                    def_hop = 60

                radio1 = {
                    "slot": 0,
                    "hop_interval": def_hop,
                    "rate": getattr(config, "RTL_AUTO_PRIMARY_RATE", config.RTL_DEFAULT_RATE),
                    "freq": config.RTL_DEFAULT_FREQ,
                }
                radio1.update(dev1)
                radio1["name"] = f"{name1} (Auto 1)"
                radios.append(radio1)

                # --- Radio #2 (Secondary) ---
                if max_radios >= 2:
                    dev2 = detected_devices[1]
                    name2 = dev2.get("name", "Secondary")

                    sec_list = [s.strip() for s in str(sec_freq).split(",") if s.strip()]

                    # If we have 3+ radios available and the plan contains multiple freqs,
                    # split them across Radio #2 and #3 to avoid hopping.
                    freq2 = sec_freq
                    hop2 = 0
                    freq3 = None

                    if max_radios >= 3 and len(detected_devices) >= 3 and len(sec_list) >= 2:
                        freq2 = sec_list[0]
                        freq3 = sec_list[1]
                        hop2 = 0
                    else:
                        if len(sec_list) >= 2:
                            hop2 = int(sec_hop or 0)
                            if hop2 <= 0:
                                hop2 = 15

                    radio2 = {
                        "slot": 1,
                        "hop_interval": hop2,
                        "rate": getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k"),
                        "freq": freq2,
                    }
                    radio2.update(dev2)
                    radio2["name"] = f"{name2} (Auto 2)"
                    radios.append(radio2)

                    # --- Radio #3 (Tertiary) ---
                    if max_radios >= 3 and len(detected_devices) >= 3:
                        dev3 = detected_devices[2]
                        name3 = dev3.get("name", "Tertiary")

                        # If Radio #3 wasn't already assigned by splitting a multi-freq secondary plan,
                        # use it as a regional "hopper" (when we know the region). This is intentionally
                        # opportunistic and may miss bursts while tuned elsewhere.
                        if not freq3:
                            hopper_override = str(getattr(config, "RTL_AUTO_HOPPER_FREQS", "") or "").strip()
                            hopper_hop = int(getattr(config, "RTL_AUTO_HOPPER_HOP_INTERVAL", 20) or 20)
                            hopper_rate = getattr(config, "RTL_AUTO_HOPPER_RATE", getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k"))

                            # Only auto-derive hopper freqs if we actually know the country.
                            if hopper_override:
                                hopper_freq = hopper_override
                            elif country:
                                # Derive a regional hopper plan that does NOT overlap with the
                                # primary/secondary radios.
                                used = {
                                    s.strip().lower()
                                    for s in str(radio1.get("freq", "")).split(",")
                                    if s.strip()
                                }
                                used.update({s.strip().lower() for s in str(freq2).split(",") if s.strip()})
                                hopper_freq = choose_hopper_band_defaults(country_code=country, used_freqs=used)
                            else:
                                hopper_freq = None

                            # If we don't have a hopper plan (unknown country and no override),
                            # fall back to the "other" band to maximize coverage.
                            if not hopper_freq:
                                f2 = str(freq2).strip().lower()
                                if f2.startswith("868"):
                                    hopper_freq = "915M"
                                elif f2.startswith("915"):
                                    hopper_freq = "868M"
                                else:
                                    hopper_freq = "915M"
                                hopper_hop = 0
                                hopper_rate = getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k")

                            # If only one frequency remains, disable hopping.
                            hopper_list = [s.strip() for s in str(hopper_freq).split(",") if s.strip()]

                            # Avoid hopping onto a band we already cover with Radio #1/#2.
                            used_freqs = {
                                s.strip().lower() for s in str(radio1.get("freq", "")).split(",") if s.strip()
                            }
                            used_freqs.update(
                                {s.strip().lower() for s in str(freq2).split(",") if s.strip()}
                            )
                            filtered = [f for f in hopper_list if f.strip().lower() not in used_freqs]
                            hopper_list = filtered

                            # If nothing remains after filtering, we refuse to overlap.
                            if not hopper_list:
                                print(
                                    "[STARTUP] Auto Multi-Radio: Radio #3 hopper has no non-overlapping bands remaining; skipping Radio #3. "
                                    "(Override rtl_auto_hopper_freqs or adjust band plan.)"
                                )
                                freq3 = None
                                hop3 = 0
                                rate3 = hopper_rate
                                # Skip creating Radio #3 entirely.
                                dev3 = None

                            if len(hopper_list) < 2:
                                hopper_hop = 0
                            else:
                                # Don't hop too aggressively; make the cycle predictable.
                                if hopper_hop < 5:
                                    hopper_hop = 5

                            freq3 = ",".join(hopper_list)
                            hop3 = hopper_hop
                            rate3 = hopper_rate
                        else:
                            hop3 = 0
                            rate3 = getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k")

                        if not dev3 or not freq3:
                            # Nothing to start for Radio #3.
                            pass
                        else:
                            radio3 = {
                                "slot": 2,
                                "hop_interval": hop3,
                                "rate": rate3,
                                "freq": freq3,
                            }
                            radio3.update(dev3)
                            radio3["name"] = f"{name3} (Auto 3)"
                            radios.append(radio3)

                for r in radios:
                    dev_name = r.get("name", "Auto")
                    warns = validate_radio_config(r)
                    for w in warns:
                        print(f"[STARTUP] DEFAULT CONFIG WARNING: [Radio: {dev_name}] {w}")

                    print(
                        f"[STARTUP] Radio #{int(r.get('slot', 0)) + 1} ({r.get('name')}) -> {r.get('freq')} (Rate: {r.get('rate')})"
                    )

                    threading.Thread(
                        target=rtl_loop,
                        args=(r, mqtt_handler, processor, sys_id, sys_model),
                        daemon=True,
                    ).start()
                    time.sleep(5)

                if len(detected_devices) > len(radios):
                    print(
                        f"[STARTUP] WARNING: [System] {len(detected_devices) - len(radios)} additional RTL-SDR(s) detected but not started in auto multi-mode. "
                        "Use rtl_config to configure them."
                    )

            else:
                print("[STARTUP] Unconfigured Mode: Starting PRIMARY radio only.")

                dev = detected_devices[0]
                dev_name = dev.get("name", "Primary")

                # 1. SMART DEFAULT LOGIC
                def_freqs = config.RTL_DEFAULT_FREQ.split(",")
                def_hop = config.RTL_DEFAULT_HOP_INTERVAL
                if len(def_freqs) < 2:
                    def_hop = 0

                radio_setup = {
                    "slot": 0,
                    "hop_interval": def_hop,
                    "rate": config.RTL_DEFAULT_RATE,
                    "freq": config.RTL_DEFAULT_FREQ
                }

                radio_setup.update(dev)

                warns = validate_radio_config(radio_setup)
                for w in warns:
                    print(f"[STARTUP] DEFAULT CONFIG WARNING: [Radio: {dev_name}] {w}")

                print(f"[STARTUP] Radio #1 ({dev['name']}) -> Defaulting to {radio_setup['freq']}")

                if len(detected_devices) > 1:
                    print(f"[STARTUP] WARNING: [System] {len(detected_devices)-1} additional SDR(s) detected but ignored. Enable Auto Multi-Radio or configure rtl_config to use them.")

                threading.Thread(
                    target=rtl_loop,
                    args=(radio_setup, mqtt_handler, processor, sys_id, sys_model),
                    daemon=True,
                ).start()
           
        else:
            # --- UPDATED: Warning for Fallback Mode ---
            print("[STARTUP] WARNING: [System] No hardware detected and no configuration provided. Attempting to start default device '0' (this will likely fail).")
            
            # 1. SMART DEFAULT LOGIC
            def_freqs = config.RTL_DEFAULT_FREQ.split(",")
            def_hop = config.RTL_DEFAULT_HOP_INTERVAL
            
            # If only 1 frequency is set, disable hopping to prevent the warning
            if len(def_freqs) < 2: 
                def_hop = 0

            auto_radio = {
                "slot": 0,
                "name": "RTL_auto", "id": "0",
                "freq": config.RTL_DEFAULT_FREQ,             
                "hop_interval": def_hop,   # <--- UPDATED: Use the calculated variable, not the config!
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