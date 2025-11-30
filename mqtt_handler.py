# mqtt_handler.py
import json
import threading
import sys
import time
import paho.mqtt.client as mqtt

# Local imports
import config
from utils import clean_mac
from field_meta import FIELD_META
import version
import logger 

class HomeNodeMQTT:
    def __init__(self):
        # Initialize MQTT Client
        self.client = mqtt.Client() 
        self.TOPIC_AVAILABILITY = f"home/status/rtl_bridge{config.ID_SUFFIX}/availability"
        if config.MQTT_SETTINGS.get("user"):
            self.client.username_pw_set(config.MQTT_SETTINGS["user"], config.MQTT_SETTINGS["pass"])
            
        self.client.will_set(self.TOPIC_AVAILABILITY, "offline", retain=True)
        self.client.on_connect = self._on_connect

        self.discovery_published = set()
        self.last_sent_values = {}
        self.tracked_devices = set()
        
        # Garbage Collection Tracking
        self.last_seen_timestamps = {}
        self.discovery_topics = {}
        
        self.discovery_lock = threading.Lock()

    def _on_connect(self, c, u, f, rc):
        if rc == 0:
            c.publish(self.TOPIC_AVAILABILITY, "online", retain=True)
        else:
            logger.error("[MQTT]", f"Connection Failed! Code: {rc}")

    def start(self):
        try:
            self.client.connect(config.MQTT_SETTINGS["host"], config.MQTT_SETTINGS["port"])
            self.client.loop_start()
        except Exception as e:
            logger.error("[CRITICAL]", f"MQTT Connect Failed: {e}")
            sys.exit(1)

    def stop(self):
        self.client.publish(self.TOPIC_AVAILABILITY, "offline", retain=True)
        self.client.loop_stop()
        self.client.disconnect()

    def _publish_discovery(self, sensor_name, state_topic, unique_id, device_name, device_model, friendly_name_override=None):
        unique_id = f"{unique_id}{config.ID_SUFFIX}"
        config_topic = f"homeassistant/sensor/{unique_id}/config"
        self.discovery_topics[unique_id] = config_topic

        with self.discovery_lock:
            if unique_id in self.discovery_published:
                return

            default_meta = (None, "none", "mdi:eye", sensor_name.replace("_", " ").title())
            if sensor_name.startswith("radio_status"):
                base_meta = FIELD_META.get("radio_status", default_meta)
            else:
                base_meta = FIELD_META.get(sensor_name, default_meta)
                
            try:
                unit, device_class, icon, default_fname = base_meta
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
            if sensor_name in getattr(config, 'MAIN_SENSORS', []) or sensor_name.startswith("radio_status"):
                entity_cat = None

            payload = {
                "name": friendly_name,
                "state_topic": state_topic,
                "unique_id": unique_id,
                "device": {
                    "identifiers": [f"rtl433_{device_model}_{unique_id.split('_')[0]}"],
                    "manufacturer": "rtl_433",
                    "model": device_model,
                    "name": device_name,
                    "sw_version": version.__version__
                },
                "icon": icon,
            }

            if unit: payload["unit_of_measurement"] = unit
            if device_class != "none": payload["device_class"] = device_class
            if entity_cat: payload["entity_category"] = entity_cat

            if device_class in ["gas", "energy", "water", "monetary"]:
                payload["state_class"] = "total_increasing"
            if device_class in ["temperature", "humidity", "pressure", "illuminance", "voltage", "signal_strength"]:
                 payload["state_class"] = "measurement"

            payload["expire_after"] = config.RTL_EXPIRE_AFTER
            payload["availability_topic"] = self.TOPIC_AVAILABILITY

            self.client.publish(config_topic, json.dumps(payload), retain=True)
            self.discovery_published.add(unique_id)

    def send_sensor(self, sensor_id, field, value, device_name, device_model, is_rtl=True, friendly_name=None):
        if value is None: return

        self.tracked_devices.add(device_name)

        clean_id = clean_mac(sensor_id) 
        unique_id_base = clean_id
        state_topic = f"home/rtl_devices/{unique_id_base}/{field}" 
        unique_id = f"{unique_id_base}_{field}"

        full_unique_id = f"{unique_id}{config.ID_SUFFIX}"
        self.last_seen_timestamps[full_unique_id] = time.time()

        self._publish_discovery(field, state_topic, unique_id, device_name, device_model, friendly_name_override=friendly_name)

        unique_id_v2 = f"{unique_id}{config.ID_SUFFIX}"
        value_changed = self.last_sent_values.get(unique_id_v2) != value

        if value_changed or is_rtl:
            self.client.publish(state_topic, str(value), retain=True)
            self.last_sent_values[unique_id_v2] = value
            
            if value_changed:
                logger.telemetry(device_name, field, value, is_rtl)

    def prune_stale_devices(self):
        """Removes devices that haven't been seen in DEVICE_PURGE_INTERVAL."""
        purge_interval = getattr(config, "DEVICE_PURGE_INTERVAL", 0)
        if not purge_interval or purge_interval <= 0: return

        now = time.time()
        to_delete = []

        for uid, last_seen in self.last_seen_timestamps.items():
            if (now - last_seen) > purge_interval:
                to_delete.append(uid)

        if to_delete:
            logger.warn("[CLEANUP]", f"Executing Purge: {len(to_delete)} Devices")
            
        for uid in to_delete:
            logger.warn("[CLEANUP]", f"Forgetting: {uid}")
            
            if uid in self.discovery_topics:
                topic = self.discovery_topics[uid]
                self.client.publish(topic, "", retain=True) 
                del self.discovery_topics[uid]

            with self.discovery_lock:
                if uid in self.discovery_published:
                    self.discovery_published.remove(uid)
            
            if uid in self.last_sent_values:
                del self.last_sent_values[uid]
            del self.last_seen_timestamps[uid]