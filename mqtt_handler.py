# mqtt_handler.py
"""
FILE: mqtt_handler.py
DESCRIPTION:
  Manages the connection to the MQTT Broker.
  - UPDATED: Removed legacy gas normalization. Now reports RAW meter values (ft3).
"""
import json
import threading
import sys
import time
import os
from datetime import datetime
# MQTT client (optional during unit tests)
try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion
except ModuleNotFoundError:  # pragma: no cover
    class CallbackAPIVersion:  # minimal shim
        VERSION2 = 2

    class _DummyMQTTClient:
        def __init__(self, *args, **kwargs):
            pass

        def username_pw_set(self, *_args, **_kwargs):
            pass

        def will_set(self, *_args, **_kwargs):
            pass

        def connect(self, *_args, **_kwargs):
            raise ModuleNotFoundError("paho-mqtt is required to use MQTT")

        def loop_start(self):
            pass

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

        def publish(self, *_args, **_kwargs):
            pass

        def subscribe(self, *_args, **_kwargs):
            pass

        def unsubscribe(self, *_args, **_kwargs):
            pass

    class _DummyMQTTModule:
        Client = _DummyMQTTClient

    mqtt = _DummyMQTTModule()
# Local imports
import config
from utils import clean_mac, get_system_mac
from field_meta import FIELD_META, get_field_meta
from rtl_manager import trigger_radio_restart

# --- Utility meter commodity inference (Itron ERT / rtlamr conventions) ---
# We infer commodity from fields like 'ert_type' (ERT-SCM) and 'MeterType' (SCMplus/IDM).
ERT_TYPE_COMMODITY = {
    "electric": {4, 5, 7, 8},
    "gas": {0, 1, 2, 9, 12},
    "water": {3, 11, 13},
}

def infer_commodity_from_ert_type(value):
    """Return 'electric'|'gas'|'water' for known ERT type values, else None."""
    try:
        t = int(value)
    except (TypeError, ValueError):
        return None
    for commodity, typeset in ERT_TYPE_COMMODITY.items():
        if t in typeset:
            return commodity
    return None

def infer_commodity_from_meter_type(value):
    """Return commodity from textual MeterType fields (e.g., 'Gas', 'Water', 'Electric')."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in {"electric", "electricity", "energy", "power"}:
        return "electric"
    if v in {"gas", "natural gas"}:
        return "gas"
    if v in {"water"}:
        return "water"
    return None


def infer_commodity_from_type_field(value):
    """Return commodity from common 'type' fields.

    rtl_433 decoders are inconsistent across meter families:
      - Some publish a textual 'type' like 'electric'/'gas'/'water'
      - Some publish a numeric ERT type under 'type'

    This helper supports both.
    """
    # Numeric ERT-style type
    if isinstance(value, (int, float)):
        return infer_commodity_from_ert_type(int(value))

    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in {"electric", "electricity", "energy", "power"}:
        return "electric"
    if v in {"gas", "natural gas"}:
        return "gas"
    if v in {"water"}:
        return "water"
    return None



def _parse_boolish(value):
    """Best-effort conversion to bool.

    Returns:
      - True / False when the value is clearly interpretable
      - None when it is not
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "on", "yes", "ok", "good"}:
            return True
        if v in {"0", "false", "off", "no", "low", "bad"}:
            return False
    return None

class HomeNodeMQTT:
    def __init__(self, version="Unknown"):
        self.sw_version = version
        self.client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        self.TOPIC_AVAILABILITY = f"home/status/rtl_bridge{config.ID_SUFFIX}/availability"
        self.client.username_pw_set(config.MQTT_SETTINGS["user"], config.MQTT_SETTINGS["pass"])
        self.client.will_set(self.TOPIC_AVAILABILITY, "offline", retain=True)
        
        # Callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.discovery_published = set()
        self.last_sent_values = {}
        self.tracked_devices = set()

        # Track one-time migrations (e.g., entity type/domain changes)
        self.migration_cleared = set()

        # Battery alert state (battery_ok -> Battery Low)
        # Keyed by clean_id (device base unique id).
        self._battery_state: dict[str, dict] = {}
        
        self.discovery_lock = threading.Lock()

        # --- Utility meter inference cache (per-device) ---
        # Used to correctly classify generic fields like 'consumption_data' for ERT-SCM endpoints.
        self._commodity_by_device = {}  # clean_id -> 'electric'|'gas'|'water'

        # Remember the last device model we saw per device.
        # Used for model-specific unit overrides (e.g., Neptune-R900 reports gallons).
        self._device_model_by_id: dict[str, str] = {}

        # Remember last raw utility readings so we can re-publish state/config
        # once we learn commodity (or unit preferences) from later fields.
        # Key: (clean_id, field) -> raw_value
        self._utility_last_raw = {}

        # Cache the last discovery signature we published per entity so we can
        # safely update HA discovery when metadata changes (e.g., gas -> energy).
        # Key: unique_id_with_suffix -> signature tuple
        self._discovery_sig = {}

        # --- Details aggregation (per-device attributes, used in minimal/balanced profiles) ---
        self._details_lock = threading.Lock()
        # clean_id -> {"attrs": {...}, "last_publish": float, "last_seen": float}
        self._details_cache: dict[str, dict] = {}

        # --- Protocol tracking (for recommended '-R ...' hints) ---
        self._protocols_lock = threading.Lock()
        self._protocols_seen: set[int] = set()

        # --- Support capture (writes raw rtl_433 JSONL to /share) ---
        self._capture_lock = threading.Lock()
        self._capture_active_until: float = 0.0
        self._capture_fp = None
        self._capture_path: str | None = None
        self._capture_last_error: str | None = None


        # --- Nuke Logic Variables ---
        self.nuke_counter = 0
        self.nuke_last_press = 0
        self.NUKE_THRESHOLD = 5       
        self.NUKE_TIMEOUT = 5.0       
        self.is_nuking = False        

    def _utility_meta_override(self, clean_id, field):
        """Return (unit, device_class, icon, friendly_name) for utility meter readings, or None."""
        commodity = self._commodity_by_device.get(clean_id)
        if not commodity:
            return None

        if commodity == "electric":
            return ("kWh", "energy", "mdi:flash", "Energy Reading")
        if commodity == "gas":
            gas_unit = str(getattr(config.settings, "gas_unit", "ft3") or "ft3").strip().lower()
            if gas_unit in {"ccf", "centum_cubic_feet"}:
                return ("CCF", "gas", "mdi:fire", "Gas Usage")
            return ("ft³", "gas", "mdi:fire", "Gas Usage")
        if commodity == "water":
            # Neptune R900 (protocol 228) typically reports gallons (often in tenths, normalized upstream).
            model = str(self._device_model_by_id.get(clean_id, "") or "").strip()
            if field == "meter_reading" and model.lower().startswith("neptune-r900"):
                return ("gal", "water", "mdi:water-pump", "Water Usage")
            return ("ft³", "water", "mdi:water-pump", "Water Reading")
        return None
    def _utility_normalize_value(self, clean_id: str, field: str, value, device_model: str):
        """Normalize utility readings *after* commodity is known.

        Goals:
          - Electric meters: ERT-SCM/SCMplus typically report hundredths of kWh.
          - Gas meters: ERT-SCM typically reports CCF (hundred cubic feet). Optionally publish ft³.
        """
        commodity = self._commodity_by_device.get(clean_id)
        if not commodity:
            return value

        # Only normalize the main utility total fields.
        if field not in {"Consumption", "consumption", "consumption_data", "meter_reading"}:
            return value

        try:
            v = float(value)
        except (TypeError, ValueError):
            return value

        model = str(device_model or self._device_model_by_id.get(clean_id, "") or "").strip().lower()

        if commodity == "electric":
            # Most ERT-SCM/SCMplus electric meters report hundredths of kWh.
            if model.startswith("ert-scm") or model.startswith("scmplus"):
                return round(v * 0.01, 2)
            return v

        if commodity == "gas":
            # rtlamr/rtl_433 commonly reports the raw counter in ft³ (which is also 0.01 CCF).
            # If you prefer billing units (CCF), we publish CCF by dividing by 100.
            gas_unit = str(getattr(config.settings, "gas_unit", "ft3") or "ft3").strip().lower()
            if gas_unit in {"ccf", "centum_cubic_feet"}:
                return round(v * 0.01, 2)
            # Default: publish ft³
            return v

        # Water (and others): do not normalize here.
        return v


    def _refresh_utility_entities_for_device(self, clean_id: str, device_name: str, device_model: str) -> None:
        """Re-publish discovery + state for cached utility readings for this device.

        This is used when we learn commodity metadata after the reading was already
        published (e.g., MeterType arrives after Consumption). Without this, HA would
        keep the first-discovered device_class/unit.
        """
        for (cid, field), raw_value in list(self._utility_last_raw.items()):
            if cid != clean_id:
                continue
            # Use is_rtl=False so we only publish if it actually changes.
            self.send_sensor(clean_id, field, raw_value, device_name, device_model, is_rtl=False)


    def _on_connect(self, c, u, f, rc, p=None):
        if rc == 0:
            c.publish(self.TOPIC_AVAILABILITY, "online", retain=True)
            print("[MQTT] Connected Successfully.")
            
            # 1. Subscribe to Nuke Command
            self.nuke_command_topic = f"home/status/rtl_bridge{config.ID_SUFFIX}/nuke/set"
            c.subscribe(self.nuke_command_topic)
            
            # 2. Subscribe to Restart Command
            self.restart_command_topic = f"home/status/rtl_bridge{config.ID_SUFFIX}/restart/set"
            c.subscribe(self.restart_command_topic)

            # 3. Subscribe to Support Capture Command
            self.capture_command_topic = f"home/status/rtl_bridge{config.ID_SUFFIX}/capture/set"
            c.subscribe(self.capture_command_topic)
            
            # 4. Publish Buttons
            self._publish_nuke_button()
            self._publish_restart_button()
            self._publish_capture_button()
        else:
            print(f"[MQTT] Connection Failed! Code: {rc}")

    def _on_message(self, client, userdata, msg):
        """Handles incoming commands AND Nuke scanning."""
        try:
            # 1. Handle Nuke Button Press
            if msg.topic == self.nuke_command_topic:
                self._handle_nuke_press()
                return

            # 2. Handle Restart Button Press
            if msg.topic == self.restart_command_topic:
                trigger_radio_restart()
                return

            # 3. Handle Capture Button Press
            if hasattr(self, "capture_command_topic") and msg.topic == self.capture_command_topic:
                self.start_capture()
                return

            # 4. Handle Nuke Scanning (Search & Destroy)
            if self.is_nuking:
                if not msg.payload: return

                try:
                    payload_str = msg.payload.decode("utf-8")
                    data = json.loads(payload_str)
                    
                    # Check Manufacturer Signature
                    device_info = data.get("device", {})
                    manufacturer = device_info.get("manufacturer", "")

                    if "rtl-haos" in manufacturer:
                        # SAFETY: Don't delete the buttons!
                        if "nuke" in msg.topic or "rtl_bridge_nuke" in str(msg.topic): return
                        if "restart" in msg.topic or "rtl_bridge_restart" in str(msg.topic): return
                        if "capture" in msg.topic or "rtl_bridge_capture" in str(msg.topic): return

                        print(f"[NUKE] FOUND & DELETING: {msg.topic}")
                        self.client.publish(msg.topic, "", retain=True)
                except Exception:
                    pass

        except Exception as e:
            print(f"[MQTT] Error handling message: {e}")

    def _publish_nuke_button(self):
        """Creates the 'Delete Entities' button."""
        sys_id = get_system_mac().replace(":", "").lower()
        unique_id = f"rtl_bridge_nuke{config.ID_SUFFIX}"
        
        payload = {
            "name": "Delete Entities (Press 5x)",
            "command_topic": self.nuke_command_topic,
            "unique_id": unique_id,
            "icon": "mdi:delete-alert",
            "entity_category": "config",
            "device": {
                "identifiers": [f"rtl433_{config.BRIDGE_NAME}_{sys_id}"],
                "manufacturer": "rtl-haos",
                "model": config.BRIDGE_NAME,
                "name": f"{config.BRIDGE_NAME} ({sys_id})",
                "sw_version": self.sw_version
            },
            "availability_topic": self.TOPIC_AVAILABILITY
        }
        
        config_topic = f"homeassistant/button/{unique_id}/config"
        self.client.publish(config_topic, json.dumps(payload), retain=True)

    def _publish_restart_button(self):
        """Creates the 'Restart Radios' button."""
        sys_id = get_system_mac().replace(":", "").lower()
        unique_id = f"rtl_bridge_restart{config.ID_SUFFIX}"
        
        payload = {
            "name": "Restart Radios",
            "command_topic": self.restart_command_topic,
            "unique_id": unique_id,
            "icon": "mdi:restart",
            "entity_category": "config",
            "device": {
                "identifiers": [f"rtl433_{config.BRIDGE_NAME}_{sys_id}"],
                "manufacturer": "rtl-haos",
                "model": config.BRIDGE_NAME,
                "name": f"{config.BRIDGE_NAME} ({sys_id})",
                "sw_version": self.sw_version
            },
            "availability_topic": self.TOPIC_AVAILABILITY
        }
        
        config_topic = f"homeassistant/button/{unique_id}/config"
        self.client.publish(config_topic, json.dumps(payload), retain=True)

    def _publish_capture_button(self):
        """Creates the 'Support Capture' button.

        When pressed, RTL-HAOS writes raw rtl_433 JSON lines (JSONL) to /share so the
        developer can inspect exactly what rtl_433 is producing.
        """
        sys_id = get_system_mac().replace(":", "").lower()
        unique_id = f"rtl_bridge_capture{config.ID_SUFFIX}"

        seconds = int(getattr(config, "CAPTURE_SECONDS", 30) or 30)

        payload = {
            "name": f"Support Capture ({seconds}s)",
            "command_topic": self.capture_command_topic,
            "unique_id": unique_id,
            "icon": "mdi:record-circle-outline",
            "entity_category": "config",
            "device": {
                "identifiers": [f"rtl433_{config.BRIDGE_NAME}_{sys_id}"],
                "manufacturer": "rtl-haos",
                "model": config.BRIDGE_NAME,
                "name": f"{config.BRIDGE_NAME} ({sys_id})",
                "sw_version": self.sw_version,
            },
            "availability_topic": self.TOPIC_AVAILABILITY,
        }

        config_topic = f"homeassistant/button/{unique_id}/config"
        self.client.publish(config_topic, json.dumps(payload), retain=True)

    def _handle_nuke_press(self):
        """Counts presses and triggers Nuke if threshold met."""
        now = time.time()
        if now - self.nuke_last_press > self.NUKE_TIMEOUT:
            self.nuke_counter = 0
        
        self.nuke_counter += 1
        self.nuke_last_press = now
        
        remaining = self.NUKE_THRESHOLD - self.nuke_counter
        
        if remaining > 0:
            print(f"[NUKE] Safety Lock: Press {remaining} more times to DETONATE.")
        else:
            self.nuke_all()
            self.nuke_counter = 0

    def nuke_all(self):
        """Activates the Search-and-Destroy protocol."""
        print("\n" + "!"*50)
        print("[NUKE] DETONATED! Scanning MQTT for 'rtl-haos' devices...")
        print("!"*50 + "\n")
        self.is_nuking = True
        self.client.subscribe("homeassistant/+/+/config")
        threading.Timer(5.0, self._stop_nuke_scan).start()

    def _stop_nuke_scan(self):
        """Stops the scanning process and resets state."""
        self.is_nuking = False
        self.client.unsubscribe("homeassistant/+/+/config")
        
        with self.discovery_lock:
            self.discovery_published.clear()
            self.last_sent_values.clear()
            self.tracked_devices.clear()
            # Also clear discovery signatures so retained config is re-published
            # even when the metadata would otherwise look "unchanged".
            self._discovery_sig.clear()

        print("[NUKE] Scan Complete. All identified entities removed.")
        self.client.publish(self.TOPIC_AVAILABILITY, "online", retain=True)
        self._publish_nuke_button()
        self._publish_restart_button()
        self._publish_capture_button()
        print("[NUKE] Host Entities restored.")

    # --- Protocol tracking ---

    def observe_protocol(self, value) -> None:
        """Record protocol IDs seen in rtl_433 output (best effort).

        Some rtl_433 builds include a numeric 'protocol' field when using '-M protocol'.
        We store these so the bridge can surface a recommended '-R ...' filter.
        """
        if value is None:
            return
        try:
            p = int(str(value).strip())
        except Exception:
            return
        if p <= 0:
            return
        with self._protocols_lock:
            self._protocols_seen.add(p)

    def get_protocols_seen(self) -> list[int]:
        with self._protocols_lock:
            return sorted(self._protocols_seen)

    def get_protocols_hint(self, max_protocols: int = 40) -> str:
        protos = self.get_protocols_seen()
        if not protos:
            return "No protocol IDs seen yet"
        shown = protos[:max_protocols]
        s = ",".join(str(p) for p in shown)
        if len(protos) > max_protocols:
            s = s + ",..."
        return f"-R {s}"

    # --- Support capture (raw JSONL) ---

    def start_capture(self, seconds: int | None = None) -> None:
        """Begin a timed capture of raw rtl_433 JSON lines to a file under /share."""
        sec_cfg = int(getattr(config, "CAPTURE_SECONDS", 30) or 30)
        seconds = int(seconds or sec_cfg)
        if seconds <= 0:
            seconds = sec_cfg
        # Safety cap: keep captures short by default to avoid filling /share.
        if seconds > 600:
            seconds = 600

        cap_dir = str(getattr(config, "CAPTURE_DIR", "/share/rtl-haos/captures") or "/share/rtl-haos/captures")
        os.makedirs(cap_dir, exist_ok=True)

        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        sys_id = get_system_mac().replace(":", "").lower()
        filename = f"rtl_433_capture_{sys_id}_{ts}.jsonl"
        path = os.path.join(cap_dir, filename)

        with self._capture_lock:
            # Stop any existing capture first
            self._capture_close_locked()
            try:
                self._capture_fp = open(path, "a", encoding="utf-8")
                self._capture_path = path
                self._capture_last_error = None
                self._capture_active_until = time.time() + seconds
            except Exception as e:
                self._capture_fp = None
                self._capture_path = None
                self._capture_last_error = f"{type(e).__name__}: {e}"
                self._capture_active_until = 0.0
                print(f"[CAPTURE] Failed to start capture: {self._capture_last_error}")
                return

        print(f"[CAPTURE] Started ({seconds}s): {path}")
        threading.Timer(seconds + 1, self.stop_capture).start()

    def _capture_close_locked(self):
        """Close capture file (lock must already be held)."""
        if self._capture_fp is not None:
            try:
                self._capture_fp.flush()
            except Exception:
                pass
            try:
                self._capture_fp.close()
            except Exception:
                pass
        self._capture_fp = None
        self._capture_active_until = 0.0

    def stop_capture(self) -> None:
        with self._capture_lock:
            if self._capture_fp is None:
                return
            path = self._capture_path
            self._capture_close_locked()
            self._capture_path = path
        print(f"[CAPTURE] Completed: {path}")

    def capture_line(self, raw_line: str) -> None:
        """Write a single JSON line to the capture file if capture is active."""
        if not raw_line:
            return
        now = time.time()
        with self._capture_lock:
            if self._capture_fp is None:
                return
            if now > (self._capture_active_until or 0.0):
                # Auto-stop if the timer didn't fire yet.
                self._capture_close_locked()
                return
            try:
                self._capture_fp.write(raw_line.rstrip("\n") + "\n")
            except Exception as e:
                self._capture_last_error = f"{type(e).__name__}: {e}"
                try:
                    self._capture_close_locked()
                except Exception:
                    pass

    def get_capture_status(self) -> str:
        with self._capture_lock:
            if self._capture_fp is None:
                if self._capture_last_error:
                    return f"idle (error: {self._capture_last_error})"
                return "idle"
            remaining = max(0, int((self._capture_active_until or 0.0) - time.time()))
            path = self._capture_path or ""
        base = os.path.basename(path) if path else ""
        return f"capturing ({remaining}s) {base}"

    # --- Details sensor ---

    def update_details(self, clean_id: str, device_name: str, device_model: str, attrs: dict, *, timestamp: str | None = None) -> None:
        """Merge attributes into a per-device Details sensor and publish on an interval."""
        if not getattr(config, "DETAILS_ENABLED", False):
            return

        if not isinstance(attrs, dict) or not attrs:
            attrs = {}

        # Always track devices even if we're not publishing field entities.
        try:
            self.tracked_devices.add(clean_id)
        except Exception:
            pass

        now = time.time()
        interval = int(getattr(config, "DETAILS_PUBLISH_INTERVAL", 30) or 30)
        max_keys = int(getattr(config, "DETAILS_MAX_KEYS", 40) or 40)
        v_max = int(getattr(config, "DETAILS_VALUE_MAXLEN", 160) or 160)
        include_keys = set(getattr(config, "DETAILS_INCLUDE_KEYS", []) or [])

        # Normalize attribute values for JSON serialization and cap string sizes.
        def _norm(v):
            if isinstance(v, (int, float, bool)) or v is None:
                return v
            # Flatten bytes, dicts, lists -> json string (bounded)
            if isinstance(v, (dict, list, tuple)):
                try:
                    s = json.dumps(v, ensure_ascii=False)
                except Exception:
                    s = str(v)
                return s[:v_max] if len(s) > v_max else s
            s = str(v)
            return s[:v_max] if len(s) > v_max else s

        with self._details_lock:
            entry = self._details_cache.get(clean_id)
            if entry is None:
                entry = {"attrs": {}, "last_publish": 0.0, "last_seen": 0.0}
                self._details_cache[clean_id] = entry

            entry["last_seen"] = now

            # Merge attrs
            a = entry.get("attrs") or {}
            for k, v in attrs.items():
                if k is None:
                    continue
                ks = str(k)
                a[ks] = _norm(v)

            # Always include last_seen and core identity fields.
            a["last_seen"] = timestamp or datetime.utcnow().isoformat(timespec="seconds") + "Z"
            a["model"] = str(device_model or "")
            a["device"] = str(device_name or "")

            # Apply max key constraint while keeping include_keys stable.
            if max_keys > 0 and len(a) > max_keys:
                # Keep include_keys + a few core keys, then add others in alpha order.
                core = {"last_seen", "model", "device"} | include_keys
                kept = {k: a[k] for k in list(a.keys()) if k in core and k in a}
                remaining_keys = [k for k in sorted(a.keys()) if k not in kept]
                for k in remaining_keys:
                    if len(kept) >= max_keys:
                        break
                    kept[k] = a[k]
                entry["attrs"] = kept
            else:
                entry["attrs"] = a

            should_publish = (entry.get("last_publish") or 0.0) == 0.0 or (now - float(entry.get("last_publish") or 0.0)) >= interval
            if should_publish:
                entry["last_publish"] = now
                payload_attrs = dict(entry["attrs"])  # shallow copy
            else:
                payload_attrs = None

        if payload_attrs is not None:
            self._publish_details_entity(clean_id, device_name, device_model, payload_attrs)

    def _publish_details_entity(self, clean_id: str, device_name: str, device_model: str, attrs: dict) -> None:
        """Publish MQTT discovery + state/attributes for the per-device Details sensor."""
        # NOTE: Home Assistant groups entities into a device by the discovery payload's
        # device.identifiers. These must remain stable across profiles (minimal/full)
        # or HA will create duplicate devices.
        unique_id = f"{clean_id}_details{config.ID_SUFFIX}"
        state_topic = f"home/rtl_devices/{clean_id}/details"
        attr_topic = f"home/rtl_devices/{clean_id}/details_attr"

        # Match the identifier strategy used by _publish_discovery so Details attaches
        # to the same HA device as the other entities for this sensor.
        device_ident = f"rtl433_{device_model}_{clean_id}"

        device_registry = {
            "identifiers": [device_ident],
            "manufacturer": "rtl-haos",
            "model": device_model,
            "name": device_name,
        }
        if device_model != config.BRIDGE_NAME:
            device_registry["via_device"] = "rtl433_" + config.BRIDGE_NAME + "_" + config.BRIDGE_ID

        payload = {
            "name": "Details",
            "state_topic": state_topic,
            "json_attributes_topic": attr_topic,
            "unique_id": unique_id,
            "icon": "mdi:information-outline",
            "entity_category": "diagnostic",
            "device": device_registry,
            "availability_topic": self.TOPIC_AVAILABILITY,
            # Keep it from expiring too aggressively; we still update last_seen in attrs.
            "expire_after": int(getattr(config, "RTL_EXPIRE_AFTER", 0) or 0) or 0,
        }

        # Re-publish retained config if metadata changes (e.g. identifiers).
        sig = (
            "sensor",
            payload.get("icon"),
            payload.get("name"),
            payload.get("json_attributes_topic"),
            tuple(payload.get("device", {}).get("identifiers", [])),
            payload.get("device", {}).get("via_device"),
        )

        prev_sig = self._discovery_sig.get(unique_id)
        if prev_sig != sig:
            config_topic = f"homeassistant/sensor/{unique_id}/config"
            self.client.publish(config_topic, json.dumps(payload), retain=True)
            with self.discovery_lock:
                self.discovery_published.add(unique_id)
            self._discovery_sig[unique_id] = sig

        # Publish attributes and a simple state
        try:
            self.client.publish(attr_topic, json.dumps(attrs, ensure_ascii=False), retain=True)
        except Exception:
            # Fallback: stringify
            self.client.publish(attr_topic, json.dumps({"error": "attrs serialization failed"}), retain=True)
        self.client.publish(state_topic, "ok", retain=True)

    def start(self):
        print(f"[STARTUP] Connecting to MQTT Broker at {config.MQTT_SETTINGS['host']}...")
        try:
            self.client.connect(config.MQTT_SETTINGS["host"], config.MQTT_SETTINGS["port"])
            self.client.loop_start()
        except Exception as e:
            print(f"[CRITICAL] MQTT Connect Failed: {e}")
            sys.exit(1)

    def stop(self):
        self.client.publish(self.TOPIC_AVAILABILITY, "offline", retain=True)
        self.client.loop_stop()
        self.client.disconnect()

    def _publish_discovery(
        self,
        sensor_name,
        state_topic,
        unique_id,
        device_name,
        device_model,
        friendly_name_override=None,
        domain="sensor",
        extra_payload=None,
        meta_override=None,
    ):
        unique_id = f"{unique_id}{config.ID_SUFFIX}"

        with self.discovery_lock:

            default_meta = (None, "none", "mdi:eye", sensor_name.replace("_", " ").title())
            
            if sensor_name.startswith("radio_status"):
                base_meta = FIELD_META.get("radio_status", default_meta)
                unit, device_class, icon, default_fname = base_meta
            else:
                meta = get_field_meta(sensor_name, device_model, base_meta=FIELD_META) or default_meta
                if meta_override is not None:
                    meta = meta_override
                try:
                    unit, device_class, icon, default_fname = meta
                except ValueError:
                    unit, device_class, icon, default_fname = default_meta

            if friendly_name_override:
                friendly_name = friendly_name_override
            elif sensor_name.startswith("radio_status_"):
                suffix = sensor_name.replace("radio_status_", "")
                friendly_name = f"{default_fname} {suffix}"
            else:
                friendly_name = default_fname

            entity_cat = "diagnostic"
            if sensor_name in getattr(config, 'MAIN_SENSORS', []):
                entity_cat = None 
            if sensor_name.startswith("radio_status"):
                entity_cat = None

            # Utility meters should not be categorized as diagnostic.
            if device_class in ["gas", "energy", "water"]:
                entity_cat = None

            device_registry = {
                "identifiers": [f"rtl433_{device_model}_{unique_id.split('_')[0]}"],
                "manufacturer": "rtl-haos",
                "model": device_model,
                "name": device_name 
            }

            if device_model != config.BRIDGE_NAME:
                device_registry["via_device"] = "rtl433_"+config.BRIDGE_NAME+"_"+config.BRIDGE_ID
            
            if device_model == config.BRIDGE_NAME:
                device_registry["sw_version"] = self.sw_version

            payload = {
                "name": friendly_name,
                "state_topic": state_topic,
                "unique_id": unique_id,
                "device": device_registry,
                "icon": icon,
            }

            # Common fields across MQTT discovery platforms
            if device_class != "none":
                payload["device_class"] = device_class
            if entity_cat:
                payload["entity_category"] = entity_cat

            # Sensor-only fields
            if domain == "sensor":
                if unit:
                    payload["unit_of_measurement"] = unit

                if device_class in ["gas", "energy", "water", "monetary", "precipitation"]:
                    payload["state_class"] = "total_increasing"
                if device_class in ["temperature", "humidity", "pressure", "illuminance", "voltage", "wind_speed", "moisture"]:
                    payload["state_class"] = "measurement"
                if device_class in ["wind_direction"]:
                    payload["state_class"] = "measurement_angle"

            if extra_payload:
                payload.update(extra_payload)

            if "version" not in sensor_name.lower() and not sensor_name.startswith("radio_status"):
                # Battery status is often reported infrequently; avoid flapping to "unavailable".
                if sensor_name == "battery_ok":
                    payload["expire_after"] = max(int(config.RTL_EXPIRE_AFTER), 86400)
                else:
                    payload["expire_after"] = config.RTL_EXPIRE_AFTER
            
            payload["availability_topic"] = self.TOPIC_AVAILABILITY

            # Signature for safe updates: if this changes, we re-publish the retained config.
            sig = (
                domain,
                payload.get("device_class"),
                payload.get("unit_of_measurement"),
                payload.get("icon"),
                payload.get("name"),
                payload.get("entity_category"),
                payload.get("state_class"),
            )

            prev_sig = self._discovery_sig.get(unique_id)
            if prev_sig == sig:
                # Already published with identical metadata.
                self.discovery_published.add(unique_id)
                return False

            config_topic = f"homeassistant/{domain}/{unique_id}/config"
            self.client.publish(config_topic, json.dumps(payload), retain=True)
            self.discovery_published.add(unique_id)
            self._discovery_sig[unique_id] = sig
            return True

    def send_sensor(self, sensor_id, field, value, device_name, device_model, is_rtl=True, friendly_name=None):
        if value is None:
            return

        self.tracked_devices.add(device_name)

        clean_id = clean_mac(sensor_id) 
        
        # Remember model for model-specific discovery/unit overrides.
        self._device_model_by_id[clean_id] = str(device_model)

        unique_id_base = clean_id
        state_topic_base = clean_id

        unique_id = f"{unique_id_base}_{field}"
        state_topic = f"home/rtl_devices/{state_topic_base}/{field}"

        # Field-specific transforms / entity types
        domain = "sensor"
        extra_payload = None
        out_value = value

        # Remember raw utility readings so we can re-publish once commodity metadata is known.
        if field in {"Consumption", "consumption", "consumption_data", "meter_reading"}:
            self._utility_last_raw[(clean_id, field)] = value


        # Commodity-aware normalization for utility meters:
        #  - Electric (ERT-SCM/SCMplus): hundredths of kWh -> kWh
        #  - Gas (ERT-SCM): CCF -> optionally publish ft³ (x100)
        # NOTE: If commodity is unknown, we publish the raw value first and
        #       automatically re-publish once commodity metadata arrives.
        prev_commodity = self._commodity_by_device.get(clean_id)

        commodity_update = None
        if field in {"ert_type", "ertType", "ERTType"}:
            commodity_update = infer_commodity_from_ert_type(value)

        if commodity_update is None and field in {"MeterType", "meter_type", "metertype"}:
            commodity_update = infer_commodity_from_meter_type(value)

        # Some decoders publish commodity hints in a generic 'type' field.
        # Only treat it as a utility hint when it looks like a commodity.
        if commodity_update is None and field in {"type", "Type"}:
            commodity_update = infer_commodity_from_type_field(value)

        if commodity_update and commodity_update != prev_commodity:
            self._commodity_by_device[clean_id] = commodity_update
            # Now that we know commodity, update any utility entities we already published.
            self._refresh_utility_entities_for_device(clean_id, device_name, device_model)

        meta_override = None
        if field in {"Consumption", "consumption", "consumption_data", "meter_reading"}:
            meta_override = self._utility_meta_override(clean_id, field)


        # Apply commodity-aware normalization for utility meter readings.
        if field in {"Consumption", "consumption", "consumption_data", "meter_reading"}:
            out_value = self._utility_normalize_value(clean_id, field, out_value, device_model)

        # battery_ok: 1/True => battery OK, 0/False => battery LOW
        # Home Assistant's binary_sensor device_class "battery" expects:
        #   ON  => low
        #   OFF => normal
        if field == "battery_ok":
            ok = _parse_boolish(value)
            if ok is None:
                return

            now = time.time()
            st = self._battery_state.setdefault(
                clean_id,
                {
                    "latched_low": False,
                    "last_low": None,
                    "ok_candidate_since": None,
                    "ok_since": None,
                },
            )

            # Update latch
            if not ok:
                st["latched_low"] = True
                st["last_low"] = now
                st["ok_candidate_since"] = None
                st["ok_since"] = None
                low = True
            else:
                if st.get("latched_low"):
                    if st.get("ok_candidate_since") is None:
                        st["ok_candidate_since"] = now

                    clear_after = int(getattr(config, "BATTERY_OK_CLEAR_AFTER", 0) or 0)
                    if clear_after <= 0 or (now - st["ok_candidate_since"]) >= clear_after:
                        st["latched_low"] = False
                        st["ok_candidate_since"] = None
                        st["ok_since"] = now
                        low = False
                    else:
                        low = True
                else:
                    # Already OK and not latched
                    if st.get("ok_since") is None:
                        st["ok_since"] = now
                    low = False

            domain = "binary_sensor"
            out_value = "ON" if low else "OFF"
            extra_payload = {"payload_on": "ON", "payload_off": "OFF"}

            # Migration helper: if an older numeric sensor existed, remove its discovery config.
            # Only do this once per runtime to avoid extra traffic.
            unique_id_v2 = f"{unique_id}{config.ID_SUFFIX}"
            if unique_id_v2 not in self.migration_cleared:
                old_sensor_config = f"homeassistant/sensor/{unique_id_v2}/config"
                self.client.publish(old_sensor_config, "", retain=True)
                with self.discovery_lock:
                    self.discovery_published.discard(unique_id_v2)
                self.migration_cleared.add(unique_id_v2)

            if friendly_name is None:
                friendly_name = "Battery Low"

        discovery_published_now = self._publish_discovery(
            field,
            state_topic,
            unique_id,
            device_name,
            device_model,
            friendly_name_override=friendly_name,
            domain=domain,
            extra_payload=extra_payload,
            meta_override=meta_override,
        )

        unique_id_v2 = f"{unique_id}{config.ID_SUFFIX}"
        value_changed = (self.last_sent_values.get(unique_id_v2) != out_value) or bool(discovery_published_now)

        if value_changed or is_rtl:
            self.client.publish(state_topic, str(out_value), retain=True)
            self.last_sent_values[unique_id_v2] = out_value

            if value_changed:
                # --- NEW: Check Verbosity Setting ---
                if config.VERBOSE_TRANSMISSIONS:
                    print(f" -> TX {device_name} [{field}]: {out_value}")