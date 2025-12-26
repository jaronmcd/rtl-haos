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

        # --- Nuke Logic Variables ---
        self.nuke_counter = 0
        self.nuke_last_press = 0
        self.NUKE_THRESHOLD = 5       
        self.NUKE_TIMEOUT = 5.0       
        self.is_nuking = False        

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

        print(f"[NUKE] Scan Complete. All identified entities removed.")
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
    ):
        unique_id = f"{unique_id}{config.ID_SUFFIX}"

        with self.discovery_lock:
            if unique_id in self.discovery_published:
                return False

            default_meta = (None, "none", "mdi:eye", sensor_name.replace("_", " ").title())
            
            if sensor_name.startswith("radio_status"):
                base_meta = FIELD_META.get("radio_status", default_meta)
                unit, device_class, icon, default_fname = base_meta
            else:
                meta = FIELD_META.get(sensor_name, default_meta)
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
                payload["expire_after"] = config.RTL_EXPIRE_AFTER
            
            payload["availability_topic"] = self.TOPIC_AVAILABILITY

            config_topic = f"homeassistant/{domain}/{unique_id}/config"
            self.client.publish(config_topic, json.dumps(payload), retain=True)
            self.discovery_published.add(unique_id)
            return True

    def send_sensor(self, sensor_id, field, value, device_name, device_model, is_rtl=True, friendly_name=None):
        if value is None:
            return

        self.tracked_devices.add(device_name)

        hide_after_publish = False
        clean_id = clean_mac(sensor_id) 
        unique_id_base = clean_id
        state_topic_base = clean_id

        unique_id = f"{unique_id_base}_{field}"
        state_topic = f"home/rtl_devices/{state_topic_base}/{field}"

        # Field-specific transforms / entity types
        domain = "sensor"
        extra_payload = None
        out_value = value


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

            # --- Optional: publish only when low ---
            with self.discovery_lock:
                discovered = unique_id_v2 in self.discovery_published

            if getattr(config, "BATTERY_PUBLISH_ONLY_WHEN_LOW", False) and not low and not discovered:
                # Track latch state but don't create a noisy entity.
                return

            # --- Optional: hide (delete discovery config) once the battery has been OK for long enough ---
            hide_when_ok = bool(getattr(config, "BATTERY_HIDE_WHEN_OK", False))
            hide_after = int(getattr(config, "BATTERY_HIDE_AFTER", 0) or 0)

            if hide_when_ok and hide_after > 0 and not low and st.get("ok_since") is not None:
                if (now - st["ok_since"]) >= hide_after:
                    if not discovered:
                        # Keep it hidden; don't recreate it.
                        return
                    hide_after_publish = True

        discovery_published_now = self._publish_discovery(
            field,
            state_topic,
            unique_id,
            device_name,
            device_model,
            friendly_name_override=friendly_name,
            domain=domain,
            extra_payload=extra_payload,
        )

        unique_id_v2 = f"{unique_id}{config.ID_SUFFIX}"
        value_changed = (self.last_sent_values.get(unique_id_v2) != out_value) or bool(discovery_published_now)

        if value_changed or is_rtl:
            self.client.publish(state_topic, str(out_value), retain=True)
            self.last_sent_values[unique_id_v2] = out_value

            if hide_after_publish:
                # Delete discovery config to remove the entity from HA.
                # This is retained and will remove the entity until we recreate it on the next LOW.
                config_topic = f"homeassistant/{domain}/{unique_id_v2}/config"
                self.client.publish(config_topic, "", retain=True)
                with self.discovery_lock:
                    self.discovery_published.discard(unique_id_v2)
                self.last_sent_values.pop(unique_id_v2, None)
            if value_changed:
                # --- NEW: Check Verbosity Setting ---
                if config.VERBOSE_TRANSMISSIONS:
                    print(f" -> TX {device_name} [{field}]: {out_value}")