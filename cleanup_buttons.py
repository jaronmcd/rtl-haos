import time
import paho.mqtt.client as mqtt
import config

# --- SETTINGS ---
TARGET_MAC = "dca632c48975" # From your logs
RESCUE_TOPIC = f"homeassistant/button/rtl_bridge_{TARGET_MAC}_purge_btn_RESCUE/config"
REAL_TOPIC   = f"homeassistant/button/rtl_bridge_{TARGET_MAC}_purge_btn/config"

def main():
    print("--- BUTTON CLEANUP TOOL ---")
    
    # Initialize Client
    if hasattr(mqtt, "CallbackAPIVersion"):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    else:
        client = mqtt.Client()
        
    if config.MQTT_SETTINGS.get("user"):
        client.username_pw_set(config.MQTT_SETTINGS["user"], config.MQTT_SETTINGS["pass"])
        
    client.connect(config.MQTT_SETTINGS["host"], config.MQTT_SETTINGS["port"])
    client.loop_start()
    time.sleep(1)

    # 1. DELETE the "Rescue" button (Send empty payload with retain=True)
    print(f"Deleting RESCUE button at: {RESCUE_TOPIC}")
    client.publish(RESCUE_TOPIC, "", retain=True)

    # 2. DELETE the "Real" button temporarily (to force HA to forget it)
    print(f"Resetting REAL button at:   {REAL_TOPIC}")
    client.publish(REAL_TOPIC, "", retain=True)
    
    print("Done. Waiting 2 seconds...")
    time.sleep(2)
    client.loop_stop()
    client.disconnect()
    print("Cleanup Complete.")

if __name__ == "__main__":
    main()