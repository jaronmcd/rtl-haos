# FILE: data_processor.py
import threading
import time
import statistics
import config

class DataProcessor:
    def __init__(self, mqtt_handler):
        self.mqtt_handler = mqtt_handler
        self.buffer = {}
        self.lock = threading.Lock()

    # UPDATED: Added radio_freq parameter (defaulting to empty string)
    def dispatch_reading(self, clean_id, field, value, dev_name, model, radio_name="Unknown", radio_freq=""):
        interval = getattr(config, "RTL_THROTTLE_INTERVAL", 0)
        
        if interval <= 0:
            self.mqtt_handler.send_sensor(clean_id, field, value, dev_name, model, is_rtl=True)
            return

        with self.lock:
            if clean_id not in self.buffer:
                self.buffer[clean_id] = {}
            
            # UPDATED: Store Frequency in Metadata
            if "__meta__" not in self.buffer[clean_id]:
                self.buffer[clean_id]["__meta__"] = {
                    "name": dev_name, 
                    "model": model, 
                    "radio": radio_name,
                    "freq": radio_freq  # <--- SAVE FREQ
                }
            else:
                self.buffer[clean_id]["__meta__"]["radio"] = radio_name
                self.buffer[clean_id]["__meta__"]["freq"] = radio_freq  # <--- UPDATE FREQ
            
            if field not in self.buffer[clean_id]:
                self.buffer[clean_id][field] = []
            
            self.buffer[clean_id][field].append(value)

    def start_throttle_loop(self):
        interval = getattr(config, "RTL_THROTTLE_INTERVAL", 30)
        if interval <= 0: return

        print(f"[THROTTLE] Averaging data every {interval} seconds.")
        
        while True:
            time.sleep(interval)
            
            with self.lock:
                if not self.buffer: continue
                current_batch = self.buffer.copy()
                self.buffer.clear()

            count_sent = 0
            stats_by_radio = {}
            
            for clean_id, device_data in current_batch.items():
                meta = device_data.get("__meta__", {})
                dev_name = meta.get("name", "Unknown")
                model = meta.get("model", "Unknown")
                r_name = meta.get("radio", "Unknown")
                r_freq = meta.get("freq", "") # <--- RETRIEVE FREQ

                for field, values in device_data.items():
                    if field == "__meta__": continue
                    if not values: continue

                    final_val = values[-1]
                    try:
                        if isinstance(values[0], (int, float)):
                            final_val = round(statistics.mean(values), 2)
                            if final_val.is_integer(): final_val = int(final_val)
                    except:
                        pass

                    self.mqtt_handler.send_sensor(clean_id, field, final_val, dev_name, model, is_rtl=True)
                    count_sent += 1
                    
                    # UPDATED: Create Composite Key for Log (Name + Freq)
                    if r_freq:
                        key = f"{r_name} ({r_freq})"
                    else:
                        key = r_name
                        
                    stats_by_radio[key] = stats_by_radio.get(key, 0) + 1
            
            if count_sent > 0:
                # Log Format: [THROTTLE] Flushed 50 readings (Linx_418 (418M): 12, RTL_Auto (433.92M): 38)
                details = ", ".join([f"{k}: {v}" for k, v in sorted(stats_by_radio.items())])
                print(f"[THROTTLE] Flushed {count_sent} readings ({details})")