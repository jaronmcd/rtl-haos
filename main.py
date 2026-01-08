#!/usr/bin/env python3
"""
FILE: main.py
DESCRIPTION:
  The main executable script.
  - UPDATED: Added explicit Warnings when NO hardware is detected on the USB bus.
  - UPDATED: Auto-renames duplicate USB serials to prevent hardware map collisions.
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
    """Return display version for logs/device info.

    Base version comes from config.yaml (VER.REV.PATCH).
    Optional internal build metadata can be supplied via RTL_HAOS_BUILD and will be
    appended as SemVer build metadata: VER.REV.PATCH+BUILD.
    """
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.yaml")
        # Prefer centralized helper (keeps one source of truth)
        from version_utils import get_display_version
        return get_display_version(cfg_path, prefix="v")
    except Exception:
        # Fallback: legacy line-scan behavior (no build metadata)
        try:
            cfg_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("version:"):
                            ver = line.split(':', 1)[1].strip()
                            ver = ver.strip().strip('"').strip("'")
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
    
    # If multiple dongles share the same USB serial (e.g., '00000001'), append index
    # (e.g., '00000001-1') so they don't overwrite each other in the hardware map.
    _seen_usb = {}
    for d in detected_devices:
        # Preserve the raw dongle-reported serial separately
        d.setdefault("usb_serial", str(d.get("id", "")).strip())

        usb = d["usb_serial"]
        if usb in _seen_usb:
            new_id = f"{usb}-{d.get('index')}"
            d["id"] = new_id
            print(
                f"[STARTUP] Renamed duplicate Serial '{usb}' to '{new_id}' "
                f"(USB Serial, index {d.get('index')})"
            )
        else:
            d["id"] = usb

        _seen_usb[usb] = True


    for d in detected_devices:
        print(
            f"[STARTUP] SDR index {d.get('index')}: "
            f"USB Serial {d.get('usb_serial')} (ID {d.get('id')}) Name {d.get('name')}"
        )


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
        print("[STARTUP] Manual mode: rtl_config is non-empty -> auto mode is disabled (rtl_auto_* settings ignored).")
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

                # --- Auto Priority (easy way to flip which band gets the first dongle) ---
                priority = str(getattr(config, "RTL_AUTO_PRIORITY", "primary") or "primary").strip().lower()
                if priority not in ("primary", "secondary", "hopper"):
                    print(f"[STARTUP] Auto Multi-Radio: rtl_auto_priority='{priority}' invalid; using 'primary'.")
                    priority = "primary"
                print(f"[STARTUP] Auto Multi-Radio: rtl_auto_priority={priority} -> first dongle role.")

                def _split_freq_list(freqs):
                    return [s.strip() for s in str(freqs).split(",") if s.strip()]

                # Build role configs (not yet bound to a specific dongle)
                def_freqs = _split_freq_list(getattr(config, "RTL_DEFAULT_FREQ", "433.92M"))
                def_hop = int(getattr(config, "RTL_DEFAULT_HOP_INTERVAL", 0) or 0)
                if len(def_freqs) < 2:
                    def_hop = 0
                elif def_hop <= 0:
                    def_hop = 60

                primary_cfg = {
                    "role": "primary",
                    "hop_interval": def_hop,
                    "rate": getattr(config, "RTL_AUTO_PRIMARY_RATE", getattr(config, "RTL_DEFAULT_RATE", "250k")),
                    "freq": getattr(config, "RTL_DEFAULT_FREQ", "433.92M"),
                }

                sec_list = _split_freq_list(sec_freq)

                # If we have 3+ radios available and the plan contains multiple freqs,
                # we normally split them across two radios to avoid hopping. If the user
                # explicitly prioritizes the hopper, we keep hopper coverage and let the
                # secondary radio hop instead.
                split_secondary = bool(
                    max_radios >= 3
                    and len(detected_devices) >= 3
                    and len(sec_list) >= 2
                    and priority in ("primary", "secondary")
                )

                secondary_split_cfg = None
                if split_secondary:
                    secondary_cfg = {
                        "role": "secondary",
                        "hop_interval": 0,
                        "rate": getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k"),
                        "freq": sec_list[0],
                    }
                    secondary_split_cfg = {
                        "role": "secondary_split",
                        "hop_interval": 0,
                        "rate": getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k"),
                        "freq": sec_list[1],
                    }
                else:
                    hop2 = 0
                    if len(sec_list) >= 2:
                        hop2 = int(sec_hop or 0)
                        if hop2 <= 0:
                            hop2 = 15
                    secondary_cfg = {
                        "role": "secondary",
                        "hop_interval": hop2,
                        "rate": getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k"),
                        "freq": sec_freq,
                    }

                # Desired role order -> which logical radio claims the first dongle
                if split_secondary:
                    if priority == "secondary":
                        plan_tokens = ["secondary", "secondary_split", "primary"]
                    else:
                        plan_tokens = ["primary", "secondary", "secondary_split"]
                else:
                    if priority == "secondary":
                        plan_tokens = ["secondary", "primary", "hopper"]
                    elif priority == "hopper":
                        plan_tokens = ["hopper", "primary", "secondary"]
                    else:
                        plan_tokens = ["primary", "secondary", "hopper"]

                tokens_to_start = plan_tokens[:max_radios]

                # Hopper role config (only if requested by token order)
                hopper_cfg = None
                if "hopper" in tokens_to_start:
                    hopper_override = str(getattr(config, "RTL_AUTO_HOPPER_FREQS", "") or "").strip()
                    hopper_hop = int(getattr(config, "RTL_AUTO_HOPPER_HOP_INTERVAL", 20) or 20)
                    hopper_rate = getattr(config, "RTL_AUTO_HOPPER_RATE", getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k"))

                    used = set()
                    for t in tokens_to_start:
                        if t == "hopper":
                            continue
                        if t == "primary":
                            used.update({s.strip().lower() for s in _split_freq_list(primary_cfg.get("freq", ""))})
                        elif t == "secondary":
                            used.update({s.strip().lower() for s in _split_freq_list(secondary_cfg.get("freq", ""))})
                        elif t == "secondary_split" and secondary_split_cfg:
                            used.update({s.strip().lower() for s in _split_freq_list(secondary_split_cfg.get("freq", ""))})

                    if hopper_override:
                        hopper_freq = hopper_override
                    elif country or priority == "hopper":
                        hopper_freq = choose_hopper_band_defaults(country_code=country, used_freqs=used)
                    else:
                        hopper_freq = None

                    if not hopper_freq:
                        # If we don't have a hopper plan (unknown country and no override),
                        # fall back to the "other" high band to maximize coverage.
                        f2 = str(secondary_cfg.get("freq", "")).strip().lower()
                        if f2.startswith("868"):
                            hopper_freq = "915M"
                        elif f2.startswith("915"):
                            hopper_freq = "868M"
                        else:
                            hopper_freq = "915M"
                        hopper_hop = 0
                        hopper_rate = getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k")

                    hopper_list = _split_freq_list(hopper_freq)

                    # Avoid hopping onto a band we already cover with the other started radios.
                    filtered = [f for f in hopper_list if f.strip().lower() not in used]
                    if not filtered:
                        if tokens_to_start and tokens_to_start[0] == "hopper":
                            print(
                                "[STARTUP] Auto Multi-Radio: Hopper has no non-overlapping bands remaining; "
                                "starting hopper with overlaps (adjust rtl_auto_hopper_freqs/band plan to refine)."
                            )
                            filtered = hopper_list
                        else:
                            print(
                                "[STARTUP] Auto Multi-Radio: Hopper has no non-overlapping bands remaining; skipping hopper radio. "
                                "(Override rtl_auto_hopper_freqs or adjust band plan.)"
                            )

                    hopper_list = filtered
                    if hopper_list:
                        if len(hopper_list) < 2:
                            hopper_hop = 0
                        else:
                            if hopper_hop < 5:
                                hopper_hop = 5

                        hopper_cfg = {
                            "role": "hopper",
                            "hop_interval": hopper_hop,
                            "rate": hopper_rate,
                            "freq": ",".join(hopper_list),
                        }

                role_map = {
                    "primary": primary_cfg,
                    "secondary": secondary_cfg,
                    "secondary_split": secondary_split_cfg,
                    "hopper": hopper_cfg,
                }

                role_label = {
                    "primary": "Primary",
                    "secondary": "Secondary",
                    "secondary_split": "Secondary (split)",
                    "hopper": "Hopper",
                }

                # Bind roles to physical dongles by order, assigning slots 0..N-1
                for slot, token in enumerate(tokens_to_start):
                    cfg = role_map.get(token)
                    if not cfg:
                        continue
                    dev = detected_devices[slot]
                    r = dict(cfg)
                    r["slot"] = slot
                    r.update(dev)
                    rid = str(r.get("id") or "").strip() or "unknown"
                    dev_name = dev.get("name", role_label.get(token, token))
                    r["name"] = f"{dev_name} (Auto {slot + 1}, {role_label.get(token, token)}, ID {rid})"
                    radios.append(r)

                for r in radios:
                    dev_name = r.get("name", "Auto")
                    warns = validate_radio_config(r)
                    for w in warns:
                        print(f"[STARTUP] DEFAULT CONFIG WARNING: [Radio: {dev_name}] {w}")

                    slot = int(r.get("slot", 0) or 0)
                    role = str(r.get("role") or "").strip() or "radio"

                    print(
                        f"[STARTUP] Radio #{slot + 1} ({role_label.get(role, role)}) ({r.get('name')}) "
                        f"[USB Serial {r.get('usb_serial', r.get('id'))} (ID {r.get('id')}) / Index {r.get('index')}] -> {r.get('freq')} "
                        f"(Rate: {r.get('rate')}, Hop: {r.get('hop_interval')})"
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

                print("[STARTUP] Unconfigured Mode: Starting single radio (auto defaults).")

                dev = detected_devices[0]

                # Easy knob: pick which auto role claims the first dongle
                priority = str(getattr(config, "RTL_AUTO_PRIORITY", "primary") or "primary").strip().lower()
                if priority not in ("primary", "secondary", "hopper"):
                    print(f"[STARTUP] Unconfigured Mode: rtl_auto_priority='{priority}' invalid; using 'primary'.")
                    priority = "primary"

                country = get_homeassistant_country_code()
                plan = getattr(config, "RTL_AUTO_BAND_PLAN", "auto")
                sec_override = str(getattr(config, "RTL_AUTO_SECONDARY_FREQ", "") or "").strip()
                sec_freq, sec_hop = choose_secondary_band_defaults(
                    plan=plan,
                    country_code=country,
                    secondary_override=sec_override,
                )

                # 1. Build the requested role config
                if priority == "secondary":
                    sec_list = [s.strip() for s in str(sec_freq).split(",") if s.strip()]
                    hop2 = 0
                    if len(sec_list) >= 2:
                        hop2 = int(sec_hop or 0)
                        if hop2 <= 0:
                            hop2 = 15
                    radio_setup = {
                        "slot": 0,
                        "role": "secondary",
                        "hop_interval": hop2,
                        "rate": getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k"),
                        "freq": sec_freq,
                    }
                elif priority == "hopper":
                    hopper_override = str(getattr(config, "RTL_AUTO_HOPPER_FREQS", "") or "").strip()
                    hopper_hop = int(getattr(config, "RTL_AUTO_HOPPER_HOP_INTERVAL", 20) or 20)
                    hopper_rate = getattr(config, "RTL_AUTO_HOPPER_RATE", getattr(config, "RTL_AUTO_SECONDARY_RATE", "1024k"))

                    if hopper_override:
                        hopper_freq = hopper_override
                    else:
                        # In single-dongle mode, allowing hopper even if HA country is unknown is the whole point.
                        hopper_freq = choose_hopper_band_defaults(country_code=country, used_freqs=set())

                    hopper_list = [s.strip() for s in str(hopper_freq).split(",") if s.strip()]
                    if len(hopper_list) < 2:
                        hopper_hop = 0
                    else:
                        if hopper_hop < 5:
                            hopper_hop = 5

                    radio_setup = {
                        "slot": 0,
                        "role": "hopper",
                        "hop_interval": hopper_hop,
                        "rate": hopper_rate,
                        "freq": ",".join(hopper_list),
                    }
                else:
                    # Primary/default behavior (433.92M)
                    def_freqs = str(getattr(config, "RTL_DEFAULT_FREQ", "433.92M")).split(",")
                    def_hop = int(getattr(config, "RTL_DEFAULT_HOP_INTERVAL", 0) or 0)
                    if len(def_freqs) < 2:
                        def_hop = 0

                    radio_setup = {
                        "slot": 0,
                        "role": "primary",
                        "hop_interval": def_hop,
                        "rate": getattr(config, "RTL_DEFAULT_RATE", "250k"),
                        "freq": getattr(config, "RTL_DEFAULT_FREQ", "433.92M"),
                    }

                radio_setup.update(dev)

                warns = validate_radio_config(radio_setup)
                for w in warns:
                    print(f"[STARTUP] DEFAULT CONFIG WARNING: [Radio: {dev.get('name','Radio')}] {w}")

                print(f"[STARTUP] Radio #1 ({dev.get('name','RTL')}) -> {radio_setup['freq']} (role={radio_setup.get('role')})")

                if len(detected_devices) > 1:
                    print(
                        f"[STARTUP] WARNING: [System] {len(detected_devices)-1} additional SDR(s) detected but ignored. "
                        "Enable Auto Multi-Radio or configure rtl_config to use them."
                    )

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