# data_processor.py
"""
FILE: data_processor.py
DESCRIPTION:
  Handles data buffering, throttling, and averaging to reduce MQTT traffic.
  - dispatch_reading(): Adds data to buffer or sends immediately if throttling is 0.
  - start_throttle_loop(): Runs in a background thread to flush averages.
  - UPDATED: Now provides consolidated summary logs.
"""
import threading
import time
import statistics
import config

class DataProcessor:
    def __init__(self, mqtt_handler):
        self.mqtt_handler = mqtt_handler
        self.buffer = {}
        self.lock = threading.Lock()

    def dispatch_reading(self, clean_id, field, value, dev_name, model):
        """
        Ingests a sensor reading.
        If throttling is disabled (interval <= 0), sends immediately.
        Otherwise, stores it in the buffer.
        """
        interval = getattr(config, "RTL_THROTTLE_INTERVAL", 0)
        
        # 1. Immediate Dispatch (No Throttling)
        if interval <= 0:
            self.mqtt_handler.send_sensor(clean_id, field, value, dev_name, model, is_rtl=True)
            return

        # 2. Buffered Dispatch
        with self.lock:
            if clean_id not in self.buffer:
                self.buffer[clean_id] = {}
            
            # Store metadata so we know who this device is when flushing
            if "__meta__" not in self.buffer[clean_id]:
                self.buffer[clean_id]["__meta__"] = {"name": dev_name, "model": model}
            
            if field not in self.buffer[clean_id]:
                self.buffer[clean_id][field] = []
            
            self.buffer[clean_id][field].append(value)

    def start_throttle_loop(self):
        """
        Thread loop that wakes up every RTL_THROTTLE_INTERVAL seconds,
        averages the buffered data, and sends it to MQTT.
        """
        interval = getattr(config, "RTL_THROTTLE_INTERVAL", 30)
        if interval <= 0:
            return

        print(f"[THROTTLE] Averaging data every {interval} seconds.")
        
        while True:
            time.sleep(interval)
            
            # 1. Swap buffers safely
            with self.lock:
                if not self.buffer:
                    continue
                current_batch = self.buffer.copy()
                self.buffer.clear()

            count_sent = 0
            
            # 2. Process batch
            for clean_id, device_data in current_batch.items():
                meta = device_data.get("__meta__", {})
                dev_name = meta.get("name", "Unknown")
                model = meta.get("model", "Unknown")

                for field, values in device_data.items():
                    if field == "__meta__": 
                        continue
                    if not values: 
                        continue

                    # Calculate Average (or last known value for strings)
                    final_val = None
                    try:
                        if isinstance(values[0], (int, float)):
                            final_val = round(statistics.mean(values), 2)
                            # If it's a whole number (like 50.0), make it int (50)
                            if final_val.is_integer(): 
                                final_val = int(final_val)
                        else:
                            final_val = values[-1]
                    except:
                        final_val = values[-1]

                    self.mqtt_handler.send_sensor(clean_id, field, final_val, dev_name, model, is_rtl=True)
                    count_sent += 1
            
            # --- NEW: Consolidated "Heartbeat" Log ---
            # This runs every 30s (default) and confirms data is flowing without spamming.
            if count_sent > 0:
                print(f"[THROTTLE] Flushed {count_sent} averaged readings to MQTT.")