# config.py
import os
import json
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

OPTIONS_PATH = "/data/options.json"
if os.path.exists(OPTIONS_PATH):
    try:
        with open(OPTIONS_PATH, "r") as f:
            options = json.load(f)
            for key, value in options.items():
                env_key = key.upper()
                if isinstance(value, (list, dict)):
                    os.environ[env_key] = json.dumps(value)
                elif value is not None and str(value).strip():
                    os.environ[env_key] = str(value)
        print(f"[CONFIG] Success! Loaded settings from Home Assistant.")
    except Exception as e:
        print(f"[CONFIG] Error loading options: {e}")

class Settings(BaseSettings):
    """Main application settings."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MQTT Settings
    mqtt_host: str = Field(default="localhost")
    mqtt_port: int = Field(default=1883)
    mqtt_user: str = Field(default="")
    mqtt_pass: str = Field(default="")
    mqtt_keepalive: int = Field(default=0)

    # --- RTL-SDR Configuration ---
    rtl_config: list[dict] = Field(default_factory=list)
    rtl_default_freq: str = Field(default="433.92M")
    rtl_default_hop_interval: int = Field(default=60)
    rtl_default_rate: str = Field(default="250k")

    bridge_id: str = Field(default="42")
    bridge_name: str = Field(default="rtl-haos-bridge")

    rtl_show_timestamps: bool = Field(
        default=False, 
        description="If True, shows 'Last: HH:MM:SS'. If False, shows 'Online'."
    )
    
    # --- NEW: VERBOSE TOGGLE ---
    verbose_transmissions: bool = Field(
        default=False, 
        description="If True, logs every single MQTT publish. If False, only logs periodic summaries."
    )

    skip_keys: list[str] = Field(default_factory=lambda: ["time", "protocol", "mod", "id"])
    device_blacklist: list[str] = Field(default_factory=lambda: ["SimpliSafe*", "EezTire*"])
    device_whitelist: list[str] = Field(default_factory=list)

    main_sensors: list[str] = Field(
        default_factory=lambda: [
            "sys_device_count", "temperature", "temperature_C", "temperature_F",
            "dew_point", "humidity", "pressure_hpa", "pressure_inhg",
            "pressure_PSI", "co2", "mics_ratio", "mq2_ratio", "mag_uT",
            "geomag_index", "wind_avg_km_h", "wind_avg_mi_h",
            "wind_gust_km_h", "wind_gust_mi_h", "wind_dir_deg", "wind_dir",
            "rain_mm", "rain_in", "rain_rate_mm_h", "rain_rate_in_h",
            "lux", "uv", "strikes", "strike_distance", "storm_dist",
            "Consumption", "consumption", "meter_reading", "moisture"
        ]
    )

    rtl_expire_after: int = Field(default=600)
    force_new_ids: bool = Field(default=False)
    debug_raw_json: bool = Field(default=False)
    rtl_throttle_interval: int = Field(default=30)

    @property
    def id_suffix(self) -> str:
        return "_v2" if self.force_new_ids else ""

settings = Settings()

BRIDGE_ID = settings.bridge_id
BRIDGE_NAME = settings.bridge_name
MQTT_SETTINGS = {
    "host": settings.mqtt_host, "port": settings.mqtt_port,
    "user": settings.mqtt_user, "pass": settings.mqtt_pass,
    "keepalive": settings.mqtt_keepalive,
}
RTL_CONFIG = settings.rtl_config
SKIP_KEYS = settings.skip_keys
DEVICE_BLACKLIST = settings.device_blacklist
DEVICE_WHITELIST = settings.device_whitelist
MAIN_SENSORS = settings.main_sensors
RTL_EXPIRE_AFTER = settings.rtl_expire_after
FORCE_NEW_IDS = settings.force_new_ids
ID_SUFFIX = settings.id_suffix
DEBUG_RAW_JSON = settings.debug_raw_json
RTL_THROTTLE_INTERVAL = settings.rtl_throttle_interval

RTL_DEFAULT_FREQ = settings.rtl_default_freq
RTL_DEFAULT_HOP_INTERVAL = settings.rtl_default_hop_interval
RTL_DEFAULT_RATE = settings.rtl_default_rate
RTL_SHOW_TIMESTAMPS = settings.rtl_show_timestamps

# EXPORT NEW SETTING
VERBOSE_TRANSMISSIONS = settings.verbose_transmissions