"""
FILE: config.py
DESCRIPTION:
  Values can be set via environment variables or a .env file.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MQTT Settings
    mqtt_host: str = Field(
        default="localhost", description="MQTT broker hostname or IP"
    )
    mqtt_port: int = Field(default=1883, description="MQTT broker port")
    mqtt_user: str = Field(default="", description="MQTT username")
    mqtt_pass: str = Field(default="", description="MQTT password")
    mqtt_keepalive: int = Field(
        default=60, description="MQTT keepalive interval in seconds"
    )

    # --- RTL-SDR Configuration ---
    
    # 1. Advanced: List of specific radio configurations (JSON/List of Dicts)
    # Example: [{"id": "0", "freq": "433.92M, 315M", "hop_interval": 60}]
    rtl_config: list[dict] = Field(
        default_factory=list, description="List of RTL-SDR radio configurations"
    )

    # 2. Simple: Defaults for Auto-Detection (Used if rtl_config is empty)
    rtl_default_freq: str = Field(
        default="433.92M",
        description="Default frequency or comma-separated list (e.g. '433.92M, 315M')"
    )
    rtl_default_hop_interval: int = Field(
        default=60,
        description="Hop interval in seconds. Only active if multiple frequencies are set."
    )

    bridge_id: str = Field(
        default="42", 
        description="Static unique ID for the bridge"
    )

    # Friendly Display Name
    bridge_name: str = Field(
        default="rtl-haos-bridge", 
        description="The friendly name shown in Home Assistant"
    )

    # Keys to skip when publishing sensor data
    skip_keys: list[str] = Field(
        default_factory=lambda: ["time", "protocol", "mod", "id"],
        description="Keys to skip when publishing",
    )

    # Device filtering
    device_blacklist: list[str] = Field(
        default_factory=lambda: ["SimpliSafe*", "EezTire*"],
        description="Device patterns to block",
    )
    device_whitelist: list[str] = Field(
        default_factory=list,
        description="If non-empty, only these device patterns are allowed",
    )

    # Main sensors (shown in main panel vs diagnostics)
    main_sensors: list[str] = Field(
        default_factory=lambda: [
            "sys_device_count",
            "temperature",
            "temperature_C",
            "temperature_F",
            "dew_point",
            "humidity",
            "pressure_hpa",
            "pressure_inhg",
            "pressure_PSI",
            "co2",
            "mics_ratio",
            "mq2_ratio",
            "mag_uT",
            "geomag_index",
            "wind_avg_km_h",
            "wind_avg_mi_h",
            "wind_gust_km_h",
            "wind_gust_mi_h",
            "wind_dir_deg",
            "wind_dir",
            "rain_mm",
            "rain_in",
            "rain_rate_mm_h",
            "rain_rate_in_h",
            "lux",
            "uv",
            "strikes",
            "strike_distance",
            "storm_dist",
            "Consumption",
            "consumption",
            "meter_reading",
        ],
        description="Sensors shown in main panel (not diagnostics)",
    )

    # Publishing settings
    rtl_expire_after: int = Field(
        default=600, description="expire_after in seconds for HA sensor entities"
    )
    force_new_ids: bool = Field(
        default=False, description="Force new unique_ids by adding suffix"
    )
    debug_raw_json: bool = Field(
        default=False, description="Print raw rtl_433 JSON to stdout"
    )

    # Throttle/averaging
    rtl_throttle_interval: int = Field(
        default=30, description="Seconds to buffer data before sending (0=realtime)"
    )

    @property
    def id_suffix(self) -> str:
        """Returns ID suffix based on force_new_ids setting."""
        return "_v2" if self.force_new_ids else ""


# Global settings instance
settings = Settings()

BRIDGE_ID = settings.bridge_id
BRIDGE_NAME = settings.bridge_name

# Convenience aliases for backward compatibility
MQTT_SETTINGS = {
    "host": settings.mqtt_host,
    "port": settings.mqtt_port,
    "user": settings.mqtt_user,
    "pass": settings.mqtt_pass,
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

# EXPORT NEW DEFAULTS
RTL_DEFAULT_FREQ = settings.rtl_default_freq
RTL_DEFAULT_HOP_INTERVAL = settings.rtl_default_hop_interval