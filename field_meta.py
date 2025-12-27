# field_meta.py
"""
FILE: field_meta.py
"""
# Format: (Unit, Device Class, Icon, Friendly Name)

FIELD_META = {
    # --- System Diagnostics (NEW: Configuration) ---
    # "sys_cfg_blacklist":    ("", "none", "mdi:playlist-remove", "Blacklist"),
    # "sys_cfg_whitelist":    ("", "none", "mdi:playlist-check", "Whitelist"),
    # "sys_cfg_sensors":      ("", "none", "mdi:eye-settings", "Main Sensors"),

    # --- System Diagnostics (Existing) ---
    "sys_device_count":     ("dev", "none", "mdi:counter", "Active Devices"),
    # "sys_device_list":      ("", "none", "mdi:format-list-bulleted", "Device List"),

    "sys_ip":               ("", "none", "mdi:ip-network", "IP Address"),
    "sys_os_version":       ("", "none", "mdi:linux", "Linux Kernel"),
    "sys_model":            ("", "none", "mdi:chip", "Device Model"),
    "sys_script_mem":       ("MB", "data_size", "mdi:memory", "Script RAM Usage"),
    "sys_cpu":              ("%", "none", "mdi:cpu-64-bit", "CPU Load"),
    "sys_mem":              ("%", "none", "mdi:memory", "RAM Usage"),
    "sys_disk":             ("%", "none", "mdi:harddisk", "Disk Usage"),
    "sys_temp":             ("°C", "temperature", "mdi:thermometer-lines", "CPU Temp"),
    "sys_uptime":           ("s", "duration", "mdi:clock-start", "System Uptime"),
    "model":                ("", "none", "mdi:tag", "Model"),

    # --- Magnetometer ---
    "mag_uT":               ("uT", "none", "mdi:magnet", "Mag Field Strength"),
    "geomag_index":         ("idx", "none", "mdi:waveform", "Mag Disturbance"),
    "status":               ("", "enum", "mdi:list-status", "Device Status"),

    # --- Temperature ---
    "temperature":          ("°F", "temperature", "mdi:thermometer", "Temperature"),
    "temperature_C":        ("°C", "temperature", "mdi:thermometer", "Temperature (C)"),
    "temperature_F":        ("°F", "temperature", "mdi:thermometer", "Temperature"),
    "dew_point":            ("°F", "temperature", "mdi:weather-fog", "Dew Point"),

    # --- Humidity ---
    "humidity":             ("%", "humidity", "mdi:water-percent", "Humidity"),

    # --- Air Quality ---
    "co2":                  ("ppm", "carbon_dioxide", "mdi:molecule-co2", "CO2 Level"),

    # --- Pressure ---
    "pressure_hpa":         ("hPa", "pressure", "mdi:gauge", "Pressure"),
    "pressure_inhg":        ("inHg", "pressure", "mdi:gauge", "Pressure"),
    "pressure_PSI":         ("psi", "pressure", "mdi:gauge", "Pressure"),

    # --- Wind ---
    "wind_avg_km_h":        ("km/h", "wind_speed", "mdi:weather-windy", "Wind Speed"),
    "wind_avg_mi_h":        ("mph", "wind_speed", "mdi:weather-windy", "Wind Speed"),
    "wind_gust_km_h":       ("km/h", "wind_speed", "mdi:weather-windy-variant", "Wind Gust"),
    "wind_gust_mi_h":       ("mph", "wind_speed", "mdi:weather-windy-variant", "Wind Gust"),
    "wind_dir_deg":         ("°", "wind_direction", "mdi:compass", "Wind Direction"),
    "wind_dir":             ("°", "wind_direction", "mdi:compass", "Wind Direction"),

    # --- Rain ---
    "rain_mm":              ("mm", "precipitation", "mdi:weather-rainy", "Rain Total"),
    "rain_in":              ("in", "precipitation", "mdi:weather-rainy", "Rain Total"),
    "rain_rate_mm_h":       ("mm/h", "precipitation_intensity", "mdi:weather-pouring", "Rain Rate"),
    "rain_rate_in_h":       ("in/h", "precipitation_intensity", "mdi:weather-pouring", "Rain Rate"),

    # --- Light ---
    "lux":                  ("lx", "illuminance", "mdi:brightness-5", "Light Level"),
    "full_lux":             ("cnt", "none", "mdi:brightness-7", "Raw Full Spectrum"),
    "ir_lux":               ("cnt", "none", "mdi:cctv", "Raw IR"),
    "uv":                   ("UV Index", "none", "mdi:sunglasses", "UV Index"),

    # --- Lightning ---
    "strikes":              ("count", "none", "mdi:flash", "Lightning Strikes"),
    "strike_distance":      ("km", "distance", "mdi:flash-alert", "Storm Distance"),
    "storm_dist":           ("km", "distance", "mdi:flash-alert", "Storm Distance"),
    "strike_count":         (None, "none", "mdi:lightning-bolt", "Strike Count"),

    # --- Soil Moisture ---
    "moisture":            ("%", "moisture", "mdi:water-percent", "Soil Moisture"),
    

    # --- Radio Diagnostics ---
    "freq":                 ("MHz", "frequency", "mdi:sine-wave", "Frequency"),
    "freq1":                ("MHz", "frequency", "mdi:sine-wave", "Frequency"),
    "freq2":                ("MHz", "frequency", "mdi:sine-wave", "Frequency"),
    "mod":                  ("", "none", "mdi:waveform", "Modulation"),
    "modulation":           ("", "none", "mdi:waveform", "Modulation"),
    "rssi":                 ("dB", "signal_strength", "mdi:wifi", "Signal (RSSI)"),
    "snr":                  ("dB", "signal_strength", "mdi:signal-distance-variant", "Signal (SNR)"),
    "noise":                ("dB", "signal_strength", "mdi:volume-high", "Noise Floor"),
    "id":                   ("", "none", "mdi:identifier", "Device ID"),
    "channel":              ("", "none", "mdi:radio-tower", "Channel"),
    "mic":                  ("", "none", "mdi:check-network", "Integrity Check"),
    "radio_status":         ("", "none", "mdi:radio-tower", "Radio Status"),
    "rfi":                  (None, "none", "mdi:radio-tower", "RFI"),
    
    # --- Utility Meters ---
    "Consumption":          ("ft³", "gas", "mdi:fire", "Gas Usage"),
    "consumption":          ("ft³", "gas", "mdi:fire", "Gas Usage"),
    "consumption_data":     ("ft³", "gas", "mdi:fire", "Gas Usage"),
    "meter_reading":        ("ft³", "water", "mdi:water-pump", "Water Reading"),

    # --- Battery ---
    # Many decoders emit battery_ok where 1/True means battery is OK and 0/False
    # means battery is LOW. We publish this as a binary sensor (device_class: battery)
    # and invert it in mqtt_handler so ON means LOW battery.
    "battery_ok":           (None, "battery", "mdi:battery", "Battery Low"),

}