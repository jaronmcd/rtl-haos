# mqtt_handler.py
"""
FILE: mqtt_handler.py
DESCRIPTION:
  Manages the connection to the MQTT Broker.
  - UPDATED: Now respects VERBOSE_TRANSMISSIONS setting.
"""
import json
import threading
import sys
import time
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
from field_meta import FIELD_META
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
            # Display units are configurable. Default is ft³.
            if str(getattr(config, "GAS_VOLUME_UNIT", "ft3")).strip().lower() == "ccf":
                return ("CCF", "gas", "mdi:fire", "Gas Usage")
            return ("ft³", "gas", "mdi:fire", "Gas Usage")
        if commodity == "water":
            # Neptune R900 (protocol 228) typically reports gallons (often in tenths, normalized upstream).
            model = str(self._device_model_by_id.get(clean_id, "") or "").strip()
            if field == "meter_reading" and model.lower().startswith("neptune-r900"):
                return ("gal", "water", "mdi:water-pump", "Water Usage")
            return ("ft³", "water", "mdi:water-pump", "Water Reading")
        return None


    def _apply_utility_value_conversion(self, clean_id: str, field: str, value):
        """Apply display-unit conversions for utility meter readings.

        Note: model-specific normalization (e.g., ÷100) happens earlier.
        This step is purely about user-facing *display units*.
        """
        commodity = self._commodity_by_device.get(clean_id)
        if commodity != "gas":
            return value

        # Gas: ft³ (default) or CCF (hundred cubic feet)
        if str(getattr(config, "GAS_VOLUME_UNIT", "ft3")).strip().lower() == "ccf":
            try:
                return round(float(value) / 100.0, 4)
            except (TypeError, ValueError):
                return value
        return value


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
            
            # 3. Publish Buttons
            self._publish_nuke_button()
            self._publish_restart_button()
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

            # 3. Handle Nuke Scanning (Search & Destroy)
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
        print("[NUKE] Host Entities restored.")

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
                meta = FIELD_META.get(sensor_name, default_meta)
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

        # Normalize raw meter readings: some models report hundredths.
        # Example: 2735618 => 27356.18 (divide by 100)
        if field in {"Consumption", "consumption", "consumption_data"}:
            scale = {"ERT-SCM": 0.01, "SCMplus": 0.01, "SCM": 0.01}.get(str(device_model).strip())
            if scale:
                try:
                    out_value = round(float(out_value) * scale, 2)
                except (TypeError, ValueError):
                    pass



        # Cache utility commodity hints.
        # ERT-SCM often uses a numeric ERT type, while SCMplus/IDM often provide MeterType.
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

        # Apply display-unit conversions AFTER normalization.
        if field in {"Consumption", "consumption", "consumption_data", "meter_reading"}:
            out_value = self._apply_utility_value_conversion(clean_id, field, out_value)

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
