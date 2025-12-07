#!/usr/bin/env python3
import time
import threading
import sys
import importlib.util
import socket
import version 
import logger

# --- IMPORTS & DEPENDENCY CHECK ---
PSUTIL_AVAILABLE = False
try:
    if importlib.util.find_spec("psutil") is not None:
        import psutil
        from sensors_system import SystemMonitor
        PSUTIL_AVAILABLE = True
    else:
        logger.info("[WARN]", "'psutil' not found. CPU/RAM stats will be disabled, but Device List will work.")
except ImportError as e:
    PSUTIL_AVAILABLE = False
    logger.info("[WARN]", f"System Monitoring disabled: {e}")

# Safe imports for the rest of the app
import config
from mqtt_handler import HomeNodeMQTT
from utils import get_system_mac 

def format_list_for_ha(data_list):
    """Joins a list into a string and truncates to ~250 chars."""
    if not data_list: return "None"
    str_list = [str(i) for i in data_list]
    joined = ", ".join(sorted(str_list))
    if len(joined) > 250: return joined[:247] + "..."
    return joined

def system_stats_loop(mqtt_handler, DEVICE_ID, MODEL_NAME):
    
    # Initialize Hardware Monitor if available
    sys_mon = None
    if PSUTIL_AVAILABLE:
        try:
            sys_mon = SystemMonitor()
            logger.info("[STARTUP]", "Hardware Monitor (psutil) initialized.")
        except Exception as e:
            logger.info("[WARN]", f"Hardware Monitor failed to start: {e}")

    full_device_name = f"{MODEL_NAME} ({DEVICE_ID})"
    
    print("[STARTUP] Starting System Monitor Loop...")

    # NOTE: Button registration is now handled automatically 
    # inside mqtt_handler._on_connect()
    
    while True:
        device_name = full_device_name

        # --- 1. BRIDGE METRICS (Always Run) ---
        try:
            devices = mqtt_handler.tracked_devices
            count = len(devices)
            mqtt_handler.send_sensor(DEVICE_ID, "sys_device_count", count, device_name, MODEL_NAME, is_rtl=True)
            mqtt_handler.send_sensor(DEVICE_ID, "sys_version", version.__version__, device_name, MODEL_NAME, is_rtl=True)
            
        except Exception as e:
            logger.info("[ERROR]", f"Bridge Stats update failed: {e}")

        # --- 2. HARDWARE METRICS (Only if psutil is working) ---
        if sys_mon:
            try:
                stats = sys_mon.read_stats()
                for key, value in stats.items(): 
                    mqtt_handler.send_sensor(DEVICE_ID, key, value, device_name, MODEL_NAME, is_rtl=True)
            except Exception as e:
                logger.info("[SYSTEM ERROR]", f"Hardware stats failed: {e}")
            
        time.sleep(60) 

if __name__ == "__main__":
    BASE_DEVICE_ID = get_system_mac().replace(":","").lower()
    BASE_MODEL_NAME = socket.gethostname().title() 
    
    print(f"--- SYSTEM MONITOR STARTING ---")

    mqtt_handler = HomeNodeMQTT()
    mqtt_handler.start()

    threading.Thread(
        target=system_stats_loop, 
        args=(mqtt_handler, BASE_DEVICE_ID, BASE_MODEL_NAME), 
        daemon=True
    ).start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping MQTT...")
        mqtt_handler.stop()