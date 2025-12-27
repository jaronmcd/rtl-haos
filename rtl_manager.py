"""
FILE: rtl_manager.py
DESCRIPTION:
  Manages the 'rtl_433' subprocess interactions.
"""
import subprocess
import json
import time
import fnmatch
import copy
import sys
from datetime import datetime
from typing import Optional

import config
from utils import clean_mac, calculate_dew_point

# --- Process Tracking ---
ACTIVE_PROCESSES = []


def _safe_status_suffix(value) -> str:
    """Return a suffix safe for use in MQTT topics and HA unique_ids."""
    if value is None:
        return "0"
    s = str(value).strip()
    if not s:
        return "0"
    out = []
    for ch in s:
        out.append(ch if ch.isalnum() else "_")
    return "".join(out)[:32]


def _derive_radio_status_field(radio_config: dict) -> str:
    """
    Derive a stable radio_status_* field name.

    Priority:
      1) status_id (explicit override; keeps legacy numbering like 0/1)
      2) id        (often SDR serial like 101/102; stable across reboots/reorder)
      3) index     (physical USB index)
      4) slot      (sequential fallback)
    """
    preferred = radio_config.get("status_id")
    if preferred is None or str(preferred).strip() == "":
        preferred = radio_config.get("id")
    if preferred is None or str(preferred).strip() == "":
        preferred = radio_config.get("index")
    if preferred is None or str(preferred).strip() == "":
        preferred = radio_config.get("slot")

    suffix = _safe_status_suffix(preferred)
    return f"radio_status_{suffix}"


def _publish_radio_status(
    mqtt_handler,
    sys_id: str,
    sys_model: str,
    status_field: str,
    status: str,
    friendly_name: Optional[str] = None,
) -> None:
    """Publish (and ensure discovery of) a host-level radio status entity."""
    # Some tests call rtl_loop(..., mqtt_handler=None) to validate CLI building.
    if mqtt_handler is None:
        return

    send = getattr(mqtt_handler, "send_sensor", None)
    if not callable(send):
        return

    host_device_name = f"{sys_model} ({sys_id})"
    send(
        sys_id,
        status_field,
        status,
        host_device_name,
        sys_model,
        is_rtl=False,
        friendly_name=friendly_name,
    )


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
            if parent:
                obj[parent] = t

    recurse(d)
    return obj
def _debug_dump_packet(
    *,
    raw_line: str,
    data_raw: dict,
    data_processed: dict,
    radio_name: str,
    radio_freq: str,
    model: str,
    clean_id: str,
) -> None:
    """
    Debug helper for reverse-engineering unknown devices.

    Highlights:
      - UNSUPPORTED = published field missing FIELD_META entry
      - Prints FIELD_META stubs for quick copy/paste
      - Preserves rtl_433's own "time" field
      - Prints raw JSON as a clean single line (no prefixes)
    """
    try:
        from field_meta import FIELD_META
    except Exception:
        FIELD_META = {}

    skip = set(getattr(config, "SKIP_KEYS", []) or [])

    rtl_time = None
    try:
        rtl_time = (data_raw or {}).get("time")
    except Exception:
        rtl_time = None

    # --- Header / summary (goes through project's print wrapper) ---
    print(
        f"[JSONDUMP] radio={radio_name} freq={radio_freq} model={model} id={clean_id} rtl_time={rtl_time or 'Unknown'}"
    )

    # --- Raw JSON (copy/paste friendly; bypass timestamped_print) ---
    print("[JSONDUMP] RAW_JSON_BEGIN (copy the next line)")
    try:
        sys.__stdout__.write(raw_line.rstrip("\n") + "\n")
        sys.__stdout__.flush()
    except Exception:
        print(raw_line)
    print("[JSONDUMP] RAW_JSON_END")

    # --- Flattened raw + processed ---
    flat_raw = flatten(data_raw or {})
    flat_proc = flatten(data_processed or {})

    def _fmt(v):
        if isinstance(v, float):
            return f"{v:.6g}"
        return repr(v)

    # Show skipped keys present (useful context)
    skipped_present = [k for k in sorted(flat_raw.keys()) if k in skip]
    if skipped_present:
        print(f"[JSONDUMP] SKIP_KEYS present (not published): {', '.join(skipped_present)}")

    print(f"[JSONDUMP] RAW keys ({len(flat_raw)}):")
    for k in sorted(flat_raw.keys()):
        v = flat_raw[k]
        t = type(v).__name__
        print(f"[JSONDUMP]   {k} = {_fmt(v)} ({t})")

    # Build the exact publish plan (mirrors rtl_loop dispatch logic).
    planned = []

    # --- Derived / special-case publishes that don't exist in the final flat dict ---
    try:
        # Neptune R900: consumption / 10 -> meter_reading
        if "Neptune-R900" in (model or ""):
            cons = (data_raw or {}).get("consumption")
            if cons is not None:
                planned.append(
                    {
                        "field": "meter_reading",
                        "value": float(cons) / 10.0,
                        "source": "Neptune-R900: consumption/10",
                    }
                )

        # SCM / ERT: consumption -> Consumption
        if (("SCM" in (model or "")) or ("ERT" in (model or ""))) and (data_raw or {}).get("consumption") is not None:
            planned.append(
                {
                    "field": "Consumption",
                    "value": (data_raw or {}).get("consumption"),
                    "source": "SCM/ERT: consumption",
                }
            )

        # Dew point: computed from temp + humidity (published separately in rtl_loop)
        t_c = (data_raw or {}).get("temperature_C")
        if t_c is None and (data_raw or {}).get("temperature_F") is not None:
            t_c = (((data_raw or {})["temperature_F"] - 32) * 5) / 9

        if t_c is not None and (data_raw or {}).get("humidity") is not None:
            dp_f = calculate_dew_point(t_c, (data_raw or {}).get("humidity"))
            if dp_f is not None:
                planned.append({"field": "dew_point", "value": dp_f, "source": "derived: dew_point"})
    except Exception:
        # Debug mode should never break the radio loop
        pass

    # --- Normal flattened publishes ---
    for key, value in flat_proc.items():
        if key in skip:
            continue

        if key in ["temperature_C", "temp_C"] and isinstance(value, (int, float)):
            planned.append({"field": "temperature", "value": round(value * 1.8 + 32.0, 1), "source": key})
        elif key in ["temperature_F", "temp_F", "temperature"] and isinstance(value, (int, float)):
            planned.append({"field": "temperature", "value": value, "source": key})
        else:
            planned.append({"field": key, "value": value, "source": key})

    # Collapse duplicates (keep first occurrence) so “derived” doesn’t spam if decoder also provides it
    seen_fields = set()
    planned_dedup = []
    for item in planned:
        f = item["field"]
        if f in seen_fields:
            continue
        seen_fields.add(f)
        planned_dedup.append(item)

    # --- Highlight support status ---
    default_icon = "mdi:eye"

    def _default_friendly(field: str) -> str:
        return field.replace("_", " ").strip().title().replace('"', "'")

    print(f"[JSONDUMP] PUBLISH plan ({len(planned_dedup)} fields):")
    missing = set()

    for item in planned_dedup:
        field = item["field"]
        value = item["value"]
        source = item["source"]

        meta = FIELD_META.get(field)

        if meta:
            unit, dev_class, icon, friendly = meta
            prefix = "[SUPPORTED]"
            meta_s = f"unit={unit or '-'} class={dev_class or '-'} icon={icon or '-'} name={friendly or '-'}"
        else:
            # This is what mqtt_handler will effectively do: default_meta
            prefix = "[UNSUPPORTED]"
            missing.add(field)
            friendly = _default_friendly(field)
            meta_s = f"FALLBACK unit=- class=none icon={default_icon} name={friendly}"

        print(f"[JSONDUMP] {prefix} {field} = {_fmt(value)}  <= {source}  {meta_s}")

    if missing:
        print(f"[JSONDUMP] unsupported fields missing FIELD_META ({len(missing)}): {', '.join(sorted(missing))}")
        print("[JSONDUMP] FIELD_META stubs (paste into field_meta.py):")
        for f in sorted(missing):
            friendly = _default_friendly(f)
            print(f'[JSONDUMP]   "{f}": (None, "none", "{default_icon}", "{friendly}"),')

    print("[JSONDUMP] END\n")


def is_blocked_device(clean_id: str, model: str, dev_type: str) -> bool:
    patterns = getattr(config, "DEVICE_BLACKLIST", [])
    for pattern in patterns:
        if fnmatch.fnmatch(str(clean_id), pattern):
            return True
        if fnmatch.fnmatch(str(model), pattern):
            return True
        if fnmatch.fnmatch(str(dev_type), pattern):
            return True
    return False


def discover_rtl_devices():
    devices = []
    index = 0
    while index < 8:
        try:
            proc = subprocess.run(
                ["rtl_eeprom", "-d", str(index)],
                capture_output=True,
                text=True,
                timeout=5,
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
    radio_name = radio_config.get("name", "Unknown")
    radio_id = radio_config.get("id", "0")

    # Host-level status entity (shows up under the Bridge device)
    status_field = _derive_radio_status_field(radio_config)

    # Optional nicer HA name (unique_id remains based on status_field)
    status_friendly = None
    if radio_name and str(radio_name).strip() and str(radio_name).strip().lower() != "unknown":
        status_friendly = f"{radio_name} Status"

    # Build Command
    cmd = ["rtl_433", "-F", "json", "-M", "level"]

    # Device selection (-d)
    dev_index = radio_config.get("index")
    if dev_index is not None:
        cmd.extend(["-d", str(dev_index)])
    else:
        cmd.extend(["-d", str(radio_id)])

    # Frequency (-f)
    freq_str = str(radio_config.get("freq", config.RTL_DEFAULT_FREQ))
    frequencies = [f.strip() for f in freq_str.split(",") if f.strip()]
    for f in frequencies:
        cmd.extend(["-f", f])

    # Hop Interval (-H)
    hop_interval = radio_config.get("hop_interval", config.RTL_DEFAULT_HOP_INTERVAL)
    if len(frequencies) > 1:
        if hop_interval <= 0:
            hop_interval = 60
        cmd.extend(["-H", str(hop_interval)])

    # Sample Rate (-s)
    rate = radio_config.get("rate", config.RTL_DEFAULT_RATE)
    cmd.extend(["-s", str(rate)])

    protocols = radio_config.get("protocols", [])
    if protocols:
        for p in protocols:
            cmd.extend(["-R", str(p)])

    freq_display = ",".join(frequencies) if frequencies else "default"

    print(f"[RTL] Starting {radio_name} on {freq_display} (Rate: {rate})...")

    # Ensure the entity exists even if no packets arrive.
    _publish_radio_status(mqtt_handler, sys_id, sys_model, status_field, "Scanning...", friendly_name=status_friendly)

    last_online_mark = 0.0
    last_error_line = None
    ts_refresh_s = 30

    while True:
        process = None
        try:
            _publish_radio_status(mqtt_handler, sys_id, sys_model, status_field, "Rebooting...", friendly_name=status_friendly)

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            ACTIVE_PROCESSES.append(process)

            _publish_radio_status(mqtt_handler, sys_id, sys_model, status_field, "Scanning...", friendly_name=status_friendly)

            empty_reads = 0

            while True:
                try:
                    line = process.stdout.readline()
                except StopIteration:
                    # Mocked stdout side_effect ran out of lines
                    break

                if line == "":
                    # Tests sometimes use "" as a “blank line” and also as EOF.
                    # Use poll + a small consecutive-empty guard to avoid infinite loops.
                    empty_reads += 1
                    if process.poll() is not None:
                        break
                    if empty_reads >= 3:
                        break
                    continue

                empty_reads = 0

                raw = line.strip()
                if not raw:
                    continue



                try:
                    data = json.loads(raw)

                    data_raw = None
                    if getattr(config, "DEBUG_RAW_JSON", False):
                        try:
                            data_raw = copy.deepcopy(data)
                        except Exception:
                            data_raw = None


                    # Mark online once we see valid JSON
                    now = time.time()
                    if config.RTL_SHOW_TIMESTAMPS:
                        if (now - last_online_mark) >= ts_refresh_s:
                            last_online_mark = now
                            stamp = datetime.now().strftime("%H:%M:%S")
                            _publish_radio_status(
                                mqtt_handler,
                                sys_id,
                                sys_model,
                                status_field,
                                f"Last: {stamp}",
                                friendly_name=status_friendly,
                            )
                    else:
                        if last_online_mark == 0.0:
                            last_online_mark = now
                            _publish_radio_status(
                                mqtt_handler, sys_id, sys_model, status_field, "Online", friendly_name=status_friendly
                            )

                    last_error_line = None

                    model = data.get("model", "Unknown")
                    raw_id = data.get("id", "Unknown")
                    clean_id = clean_mac(raw_id)
                    dev_name = f"{model} {clean_id}"
                    dev_type = data.get("type", "Untyped")

                    if is_blocked_device(clean_id, model, dev_type):
                        continue

                    whitelist = getattr(config, "DEVICE_WHITELIST", [])
                    if whitelist and not any(fnmatch.fnmatch(clean_id, p) for p in whitelist):
                        continue

                    # Neptune R900 Water Meter
                    if "Neptune-R900" in model and data.get("consumption") is not None:
                        real_val = float(data["consumption"]) / 10.0
                        data_processor.dispatch_reading(
                            clean_id, "meter_reading", real_val, dev_name, model, radio_name=radio_name, radio_freq=freq_display
                        )
                        del data["consumption"]

                    # SCM / ERT Meters
                    if ("SCM" in model or "ERT" in model) and data.get("consumption") is not None:
                        data_processor.dispatch_reading(
                            clean_id, "Consumption", data["consumption"], dev_name, model, radio_name=radio_name, radio_freq=freq_display
                        )
                        del data["consumption"]

                    # Dew point
                    t_c = data.get("temperature_C")
                    if t_c is None and "temperature_F" in data:
                        t_c = (data["temperature_F"] - 32) * 5 / 9

                    if t_c is not None and data.get("humidity") is not None:
                        dp_f = calculate_dew_point(t_c, data["humidity"])
                        if dp_f is not None:
                            data_processor.dispatch_reading(
                                clean_id, "dew_point", dp_f, dev_name, model, radio_name=radio_name, radio_freq=freq_display
                            )

                    # Flatten + dispatch
                    # Flatten + dispatch
                    if getattr(config, "DEBUG_RAW_JSON", False):
                        _debug_dump_packet(
                            raw_line=raw,
                            data_raw=data_raw or data,
                            data_processed=data,
                            radio_name=radio_name,
                            radio_freq=freq_display,
                            model=model,
                            clean_id=clean_id,
                        )

                    flat = flatten(data)
                    for key, value in flat.items():
                        if key in getattr(config, "SKIP_KEYS", []):
                            continue

                        if key in ["temperature_C", "temp_C"] and isinstance(value, (int, float)):
                            val_f = round(value * 1.8 + 32.0, 1)
                            data_processor.dispatch_reading(
                                clean_id, "temperature", val_f, dev_name, model, radio_name=radio_name, radio_freq=freq_display
                            )
                        elif key in ["temperature_F", "temp_F", "temperature"] and isinstance(value, (int, float)):
                            data_processor.dispatch_reading(
                                clean_id, "temperature", value, dev_name, model, radio_name=radio_name, radio_freq=freq_display
                            )
                        else:
                            data_processor.dispatch_reading(
                                clean_id, key, value, dev_name, model, radio_name=radio_name, radio_freq=freq_display
                            )

                except json.JSONDecodeError:
                    # Logs/errors from rtl_433 / librtlsdr
                    low = raw.lower()

                    # Ignore common noise
                    if "detached kernel driver" in low or "detaching kernel driver" in low:
                        continue

                    # --- Friendly HA status mappings (check BEFORE noise filters) ---
                    status = None
                    if "no supported devices" in low or "no matching device" in low or "found 0 device" in low:
                        status = "Error: No RTL-SDR device found"
                    elif "usb_claim_interface" in low or "device or resource busy" in low:
                        status = "Error: USB busy / claimed"
                    elif "permission denied" in low:
                        status = "Error: Permission denied"
                    elif "kernel driver is active" in low:
                        status = "Error: Kernel driver active"
                    elif "illegal instruction" in low or "segmentation fault" in low:
                        status = "Error: rtl_433 crashed"

                    if status is not None:
                        last_error_line = raw[:160]
                        _publish_radio_status(
                            mqtt_handler,
                            sys_id,
                            sys_model,
                            status_field,
                            status,
                            friendly_name=status_friendly,
                        )
                        continue

                    # Ignore startup chatter that isn't actionable
                    if "using device" in low or ("found" in low and "device" in low):
                        continue
                except Exception as e:
                    print(f"[RTL] Error processing line: {e}")

        except Exception as e:
            _publish_radio_status(mqtt_handler, sys_id, sys_model, status_field, f"Error: {e}", friendly_name=status_friendly)
            print(f"[RTL] Subprocess crashed or failed to start: {e}")

        # Cleanup before restart
        if process:
            if process in ACTIVE_PROCESSES:
                ACTIVE_PROCESSES.remove(process)

            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

            rc = process.poll()
            if rc is not None and rc != 0:
                if last_error_line:
                    _publish_radio_status(
                        mqtt_handler, sys_id, sys_model, status_field, f"Error: {last_error_line}", friendly_name=status_friendly
                    )
                else:
                    _publish_radio_status(
                        mqtt_handler, sys_id, sys_model, status_field, f"Error: rtl_433 exited ({rc})", friendly_name=status_friendly
                    )

        last_online_mark = 0.0
        print(f"[RTL] {radio_name} crashed/stopped. Restarting in 5s...")
        time.sleep(5)
