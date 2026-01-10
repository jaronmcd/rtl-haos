# data_processor.py
"""
FILE: data_processor.py
DESCRIPTION:
  Handles data buffering, throttling, and averaging to reduce MQTT traffic.
  - dispatch_reading(): Adds data to buffer or sends immediately if throttling is 0.
  - start_throttle_loop(): Runs in a background thread to flush averages.
  - UPDATED: Now accepts and logs 'radio_freq'.
"""
import threading
import time
import statistics

import config
from field_meta import get_field_meta


# Numeric fields that should NOT be averaged during throttling.
# Instead, we publish a last/max value based on what makes sense for HA statistics.
#
# Why: averaging counters/totals (e.g. water/gas totals) corrupts HA long-term stats,
# and averaging angles (wind direction) is mathematically wrong.
NON_AVERAGED_NUMERIC_FIELDS = {
    # Battery OK is latched/translated downstream; never average.
    "battery_ok",
}


def _aggregation_mode(field: str, device_model: str | None) -> str:
    """Return aggregation mode for a field during throttling.

    Modes:
      - "mean": arithmetic mean (default for continuous measurements)
      - "last": last observed value in the interval
      - "max": max observed value in the interval
    """
    f = str(field or "").strip()
    f_l = f.lower()

    if f in NON_AVERAGED_NUMERIC_FIELDS:
        return "last"

    # Wind direction is an angle; averaging 359 and 1 should not yield 180.
    if f_l in {"wind_dir", "wind_dir_deg"}:
        return "last"

    # Gusts and signal quality are typically better represented by peak.
    if "gust" in f_l:
        return "max"
    if f_l in {"rssi", "snr", "noise", "rssi_db", "snr_db", "noise_db"}:
        return "max"

    # Many decoders emit counters/totals; averaging can create fractional values and
    # break monotonic expectations. Use last value.
    if f_l in {"counter", "sequence", "strikes", "strike_count"}:
        return "last"

    # Consult field metadata (model-aware) when available.
    meta = get_field_meta(f, device_model)
    if meta:
        unit, device_class, _icon, _name = meta
        # These are published as total_increasing in mqtt_handler.
        if device_class in {"gas", "energy", "water", "precipitation"}:
            return "last"

    return "mean"

class DataProcessor:
    def __init__(self, mqtt_handler):
        self.mqtt_handler = mqtt_handler
        self.buffer = {}
        self.lock = threading.Lock()

    # --- FIX 1: Add radio_freq to arguments ---
    def dispatch_reading(self, clean_id, field, value, dev_name, model, radio_name="Unknown", radio_freq="Unknown"):
        """
        Ingests a sensor reading.
        If throttling is disabled (interval <= 0), sends immediately.
        Otherwise, stores it in the buffer.
        """
        interval = getattr(config, "RTL_THROTTLE_INTERVAL", 0)

        # Skip null readings; they shouldn't influence averages or "last known" decisions.
        if value is None:
            return
        
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
                self.buffer[clean_id]["__meta__"] = {
                    "name": dev_name, 
                    "model": model, 
                    "radio": radio_name,
                    "freq": radio_freq  # --- FIX 2: Store the frequency ---
                }
            else:
                self.buffer[clean_id]["__meta__"]["radio"] = radio_name
                self.buffer[clean_id]["__meta__"]["freq"] = radio_freq
            
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
            stats_by_radio = {}
            
            # 2. Process batch
            for clean_id, device_data in current_batch.items():
                meta = device_data.get("__meta__", {})
                dev_name = meta.get("name", "Unknown")
                model = meta.get("model", "Unknown")
                r_name = meta.get("radio", "Unknown")
                r_freq = meta.get("freq", "")

                for field, values in device_data.items():
                    if field == "__meta__": 
                        continue
                    if not values: 
                        continue

                    # Aggregate values collected during the interval.
                    # Default: mean for continuous measurements; last/max for totals/counters/angles.
                    final_val = None
                    try:
                        mode = _aggregation_mode(field, model)

                        if not isinstance(values[0], (int, float)):
                            # Strings / enums: always publish the last observed value.
                            final_val = values[-1]
                        elif mode == "last":
                            final_val = values[-1]
                        elif mode == "max":
                            final_val = max(values)
                        else:
                            # mean
                            final_val = round(statistics.mean(values), 2)

                        # Avoid publishing floats for integer-like readings.
                        if isinstance(final_val, float) and final_val.is_integer():
                            final_val = int(final_val)
                    except Exception:
                        final_val = values[-1]

                    self.mqtt_handler.send_sensor(clean_id, field, final_val, dev_name, model, is_rtl=True)
                    count_sent += 1
                    
                    # --- FIX 3: Group by Radio + Frequency for the log ---
                    key = f"{r_name}"
                    if r_freq and r_freq != "Unknown":
                        key = f"{r_name}[{r_freq}]"
                        
                    stats_by_radio[key] = stats_by_radio.get(key, 0) + 1
            
            # --- Consolidated Heartbeat Log ---
            if count_sent > 0:
                # Format: (RTL_101[915M]: 5, RTL_001[433.92M]: 3)
                details = ", ".join([f"{k}: {v}" for k, v in stats_by_radio.items()])
                print(f"[THROTTLE] Flushed {count_sent} readings ({details})")