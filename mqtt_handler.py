# mqtt_handler.py
"""
FILE: mqtt_handler.py
DESCRIPTION:
  Manages the connection to the MQTT Broker.
  - UPDATED: 
    1. 'Nuke' now immediately resurrects the Host Bridge entities 
       (Status, Button, Availability) so the UI doesn't look broken.
"""
import json
import threading
import sys
import time
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
# Local imports
import config
from utils import clean_mac, get_system_mac
from field_meta import FIELD_META

class HomeNodeMQTT:
    def __init__(self):
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
            
            # 2. Publish the Nuke Button
            self._publish_nuke_button()
        else:
            print(f"[MQTT] Connection Failed! Code: {rc}")

    def _on_message(self, client, userdata, msg):
        """Handles incoming commands AND Nuke scanning."""
        try:
            # 1. Handle Nuke Button Press
            if msg.topic == self.nuke_command_topic:
                self._handle_nuke_press()
                return

            # 2. Handle Nuke Scanning (Search & Destroy)
            if self.is_nuking:
                if not msg.payload: return

                try:
                    payload_str = msg.payload.decode("utf-8")
                    data = json.loads(payload_str)
                    
                    # Check Manufacturer Signature
                    device_info = data.get("device", {})
                    manufacturer = device_info.get("manufacturer", "")

                    if "rtl-haos" in manufacturer:
                        # SAFETY: Don't delete the Nuke button itself!
                        if "nuke" in msg.topic or "rtl_bridge_nuke" in str(msg.topic):
                            return

                        print(f"[NUKE] FOUND & DELETING: {msg.topic}")
                        self.client.publish(msg.topic, "", retain=True)
                except Exception:
                    pass

        except Exception as e:
            print(f"[MQTT] Error handling message: {e}")

    def _publish_nuke_button(self):
        """Creates the 'Nuke Entities' button on the Bridge device."""
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
                "name": f"{config.BRIDGE_NAME} ({sys_id})"
            },
            "availability_topic": self.TOPIC_AVAILABILITY
        }
        
        config_topic = f"homeassistant/button/{unique_id}/config"
        self.client.publish(config_topic, json.dumps(payload), retain=True)

    def _handle_nuke_press(self):
        """Counts presses and triggers Nuke if threshold met."""
        now = time.time()
        
        # Reset if too much time passed
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
        
        # Subscribe to ALL Home Assistant config topics (Wildcard)
        self.client.subscribe("homeassistant/+/+/config")
        
        # Schedule the scan to stop in 5 seconds
        threading.Timer(5.0, self._stop_nuke_scan).start()

    def _stop_nuke_scan(self):
        """Stops the scanning process and resets state."""
        self.is_nuking = False
        self.client.unsubscribe("homeassistant/+/+/config")
        
        # 1. Clear Internal Memory (So we know to re-publish everything)
        with self.discovery_lock:
            self.discovery_published.clear()
            self.last_sent_values.clear()
            self.tracked_devices.clear()

        print(f"[NUKE] Scan Complete. All identified entities removed.")
        
        # 2. IMMEDIATE RESURRECTION
        # Re-assert that the Bridge is online
        self.client.publish(self.TOPIC_AVAILABILITY, "online", retain=True)
        
        # Re-publish the Nuke Button immediately (so it doesn't vanish)
        self._publish_nuke_button()
        
        print("[NUKE] Host Entities restored. Sensor data (CPU/RAM) will return shortly.")

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

    def _publish_discovery(self, sensor_name, state_topic, unique_id, device_name, device_model, friendly_name_override=None):
        unique_id = f"{unique_id}{config.ID_SUFFIX}"

        with self.discovery_lock:
            if unique_id in self.discovery_published:
                return

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

            payload = {
                "name": friendly_name,
                "state_topic": state_topic,
                "unique_id": unique_id,
                "device": {
                    "identifiers": [f"rtl433_{device_model}_{unique_id.split('_')[0]}"],
                    "manufacturer": "rtl-haos",
                    "model": device_model,
                    "name": device_name 
                },
                "icon": icon,
            }

            if unit: payload["unit_of_measurement"] = unit
            if device_class != "none": payload["device_class"] = device_class
            if entity_cat: payload["entity_category"] = entity_cat

            if device_class in ["gas", "energy", "water", "monetary", "precipitation"]:
                payload["state_class"] = "total_increasing"
            if device_class in ["temperature", "humidity", "pressure", "illuminance", "voltage","wind_speed"]:
                payload["state_class"] = "measurement"
            if device_class in ["wind_direction"]:
                payload["state_class"] = "measurement_angle"

            if "version" not in sensor_name.lower():
                payload["expire_after"] = config.RTL_EXPIRE_AFTER
            payload["availability_topic"] = self.TOPIC_AVAILABILITY

            config_topic = f"homeassistant/sensor/{unique_id}/config"
            self.client.publish(config_topic, json.dumps(payload), retain=True)
            self.discovery_published.add(unique_id)

    def send_sensor(self, sensor_id, field, value, device_name, device_model, is_rtl=True, friendly_name=None):
        if value is None: return

        self.tracked_devices.add(device_name)

        clean_id = clean_mac(sensor_id) 
        unique_id_base = clean_id
        state_topic_base = clean_id

        unique_id = f"{unique_id_base}_{field}"
        state_topic = f"home/rtl_devices/{state_topic_base}/{field}" 

        self._publish_discovery(field, state_topic, unique_id, device_name, device_model, friendly_name_override=friendly_name)

        unique_id_v2 = f"{unique_id}{config.ID_SUFFIX}"
        
        value_changed = self.last_sent_values.get(unique_id_v2) != value

        if value_changed or is_rtl:
            self.client.publish(state_topic, str(value), retain=True)
            self.last_sent_values[unique_id_v2] = value
            
            if value_changed:
                print(f" -> TX {device_name} [{field}]: {value}")