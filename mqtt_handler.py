# mqtt_handler.py
import json
import threading
import sys
import time
import socket
import paho.mqtt.client as mqtt

# Local imports
import config
from utils import clean_mac, get_system_mac
from field_meta import FIELD_META
import version
import logger 

class HomeNodeMQTT:
    def __init__(self):
        # Initialize MQTT Client (Paho 2.0 compatible)
        if hasattr(mqtt, "CallbackAPIVersion"):
             self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        else:
             self.client = mqtt.Client()

        self.sys_id = get_system_mac().replace(":", "").lower()
        self.sys_model = socket.gethostname().title() 
        self.TOPIC_AVAILABILITY = f"home/status/rtl_bridge{config.ID_SUFFIX}/availability"
        
        if config.MQTT_SETTINGS.get("user"):
            self.client.username_pw_set(config.MQTT_SETTINGS["user"], config.MQTT_SETTINGS["pass"])
            
        self.client.will_set(self.TOPIC_AVAILABILITY, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message 

        self.discovery_published = set()
        self.last_sent_values = {}
        self.tracked_devices = set()
        
        self.last_seen_timestamps = {}
        self.discovery_topics = {}
        self.discovery_lock = threading.Lock()
        
        # Safety Systems
        self.nuke_active = False
        self.nuke_last_click = 0
        self.nuke_tap_count = 0

    def _on_connect(self, c, u, f, rc, props=None):
        if rc == 0:
            c.publish(self.TOPIC_AVAILABILITY, "online", retain=True)
            # Subscribe to command topics
            cmd_topic = f"home/rtl_bridge/{self.sys_id}/commands/#"
            c.subscribe(cmd_topic)
            
            # Publish Admin Buttons
            self.publish_admin_buttons()
        else:
            logger.error("[MQTT]", f"Connection Failed! Code: {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode()
            now = time.time()
            
            # --- 1. COMMAND HANDLING ---
            if msg.topic.endswith("/purge") and payload == "PRESS":
                logger.info("[COMMAND]", "Force Purge Triggered")
                self.prune_stale_devices(force=True)
                return

            if msg.topic.endswith("/nuke") and payload == "PRESS":
                # --- 5-TAP SAFETY LOGIC ---
                time_since_last = now - self.nuke_last_click
                
                # Reset count if it's been more than 5 seconds since last click
                if time_since_last > 5.0:
                    self.nuke_tap_count = 0
                
                self.nuke_tap_count += 1
                self.nuke_last_click = now
                
                clicks_needed = 5 - self.nuke_tap_count
                
                if clicks_needed <= 0:
                    logger.warn("[NUKE]", "🚨 ACTIVATION CONFIRMED. EXECUTING WIPE. 🚨")
                    self.perform_nuclear_option()
                    self.nuke_tap_count = 0 # Reset
                else:
                    logger.warn("[NUKE]", f"⚠️ ARMED! {clicks_needed} MORE CLICKS TO DETONATE... ⚠️")
                return

            # --- 2. NUKE SCANNING (Only active during Nuke Mode) ---
            if self.nuke_active and msg.topic.startswith("homeassistant"):
                try:
                    data = json.loads(payload)
                    dev_manufacturer = data.get("device", {}).get("manufacturer", "")
                    
                    # If matches our signature "rtl-haos", DESTROY IT.
                    if dev_manufacturer == "rtl-haos":
                        logger.warn("[NUKE]", f"Deleting Ghost: {msg.topic}")
                        client.publish(msg.topic, "", retain=True)
                except:
                    pass

        except Exception as e:
            pass

    def perform_nuclear_option(self):
        """Activates 'Search and Destroy' mode for 5 seconds."""
        if self.nuke_active: return
        
        logger.warn("[NUKE]", "☢️ NUCLEAR LAUNCH DETECTED ☢️")
        logger.warn("[NUKE]", "Scanning for ALL rtl-haos devices...")
        
        self.nuke_active = True
        # Subscribe to ALL discovery topics to find ghosts
        self.client.subscribe("homeassistant/+/+/config")
        
        # Schedule the 'All Clear' in 5 seconds
        threading.Timer(5.0, self._stop_nuke).start()

    def _stop_nuke(self):
        """Stops the nuke process and restores admin buttons."""
        self.client.unsubscribe("homeassistant/+/+/config")
        self.nuke_active = False
        logger.info("[NUKE]", "Wipe Complete. Restoring System...")
        
        # Re-publish buttons
        self.publish_admin_buttons()
        
        # Clear internal memory so we can rediscover fresh
        self.discovery_published.clear()
        self.tracked_devices.clear()
        self.last_sent_values.clear()
        self.last_seen_timestamps.clear()

    def publish_admin_buttons(self):
        """Publishes Purge and Nuke buttons."""
        device_name = f"{self.sys_model} ({self.sys_id})"
        identifier = f"rtl433_{self.sys_model}_{self.sys_id}"
        
        # --- BUTTON 1: FORCE PURGE ---
        self._pub_btn(
            "Force Purge Stale", "purge", "mdi:broom", 
            device_name, identifier
        )

        # --- BUTTON 2: DEV NUKE (5x TAP) ---
        self._pub_btn(
            "DESTROY ALL (5x Tap)", "nuke", "mdi:nuke", 
            device_name, identifier, category="config"
        )

    def _pub_btn(self, name, slug, icon, dev_name, identifier, category="config"):
        unique_id = f"rtl_bridge_{self.sys_id}_{slug}_btn{config.ID_SUFFIX}"
        config_topic = f"homeassistant/button/{unique_id}/config"
        command_topic = f"home/rtl_bridge/{self.sys_id}/commands/{slug}"

        payload = {
            "name": name,
            "unique_id": unique_id,
            "command_topic": command_topic,
            "payload_press": "PRESS",
            "icon": icon,
            "device": {
                "identifiers": [identifier], 
                "manufacturer": "rtl-haos",
                "model": self.sys_model,
                "name": dev_name,
                "sw_version": version.__version__
            },
            "entity_category": category,
            "availability_topic": self.TOPIC_AVAILABILITY
        }
        self.client.publish(config_topic, json.dumps(payload), retain=True)

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
                    "manufacturer": "rtl-haos",
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

    def prune_stale_devices(self, force=False):
        purge_interval = getattr(config, "DEVICE_PURGE_INTERVAL", 0)
        
        if not purge_interval or purge_interval <= 0: 
            if force:
                logger.warn("[CLEANUP]", "Purge skipped: DEVICE_PURGE_INTERVAL is 0.")
            return

        now = time.time()
        to_delete = []

        for uid, last_seen in self.last_seen_timestamps.items():
            if (now - last_seen) > purge_interval:
                to_delete.append(uid)

        if to_delete:
            logger.warn("[CLEANUP]", f"Executing Purge: {len(to_delete)} Devices")
        elif force:
            logger.info("[CLEANUP]", "Manual Purge scan complete. No stale devices found.")
            
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