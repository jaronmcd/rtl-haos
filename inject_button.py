# inject_button.py
import time
import json
import paho.mqtt.client as mqtt
import config

# --- CONFIGURATION MATCHING YOUR SYSTEM ---
TARGET_MAC = "dca632c48975"
TARGET_MODEL = "P-Yardstick"
DEVICE_IDENTIFIER = f"rtl433_{TARGET_MODEL}_{TARGET_MAC}"

def main():
    print(f"--- BUTTON INJECTOR ---")
    print(f"Target Broker: {config.MQTT_SETTINGS['host']}")
    print(f"Target Device: {DEVICE_IDENTIFIER}")

    # --- FIX FOR PAHO MQTT 2.0 ---
    # We check if the new API version enum exists.
    if hasattr(mqtt, "CallbackAPIVersion"):
        # New Paho 2.0+ Syntax
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Button_Injector_Tool")
    else:
        # Old Paho 1.x Syntax
        client = mqtt.Client("Button_Injector_Tool")

    # --- CREDENTIALS ---
    if config.MQTT_SETTINGS.get("user"):
        print(f"Using Credentials: User '{config.MQTT_SETTINGS['user']}' found.")
        client.username_pw_set(config.MQTT_SETTINGS["user"], config.MQTT_SETTINGS["pass"])
    
    try:
        client.connect(config.MQTT_SETTINGS["host"], config.MQTT_SETTINGS["port"])
        client.loop_start()
        time.sleep(1) # Wait for connection
    except Exception as e:
        print(f"[ERROR] Could not connect to MQTT: {e}")
        return

    # 1. Define the Button Payload
    unique_id = f"rtl_bridge_{TARGET_MAC}_purge_btn_RESCUE"
    config_topic = f"homeassistant/button/{unique_id}/config"
    command_topic = f"home/rtl_bridge/{TARGET_MAC}/commands/purge"

    payload = {
        "name": "Force Purge Stale (Rescue)",
        "unique_id": unique_id,
        "command_topic": command_topic,
        "payload_press": "PRESS",
        "icon": "mdi:broom",
        "device": {
            # This links the button to your existing P-Yardstick device
            "identifiers": [DEVICE_IDENTIFIER], 
            "manufacturer": "rtl-haos",
            "model": TARGET_MODEL,
            "name": f"{TARGET_MODEL} ({TARGET_MAC})" 
        },
        "entity_category": "config"
    }

    # 2. Publish
    print(f"Sending payload to: {config_topic}")
    info = client.publish(config_topic, json.dumps(payload), retain=True)
    info.wait_for_publish()
    
    print("Payload SENT.")
    print("Check Home Assistant now.")
    
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()