# utils.py
"""
FILE: utils.py
DESCRIPTION:
  Shared helper functions used across the project.
  - clean_mac(): Sanitizes device IDs for MQTT topics.
  - calculate_dew_point(): Math formula to calculate Dew Point from Temp/Humidity.
  - get_system_mac(): Generates a unique ID for the bridge itself based on hardware.
  - validate_radio_config(): Checks for common configuration mistakes (Missing M, Missing ID, etc).
"""
import re
import math
import socket
import os
import json
import config

# Global cache
_SYSTEM_MAC = None

def get_system_mac():
    global _SYSTEM_MAC
    if _SYSTEM_MAC: 
        return _SYSTEM_MAC

    # 1. PREFERRED: Use Static ID from Config
    if config.BRIDGE_ID:
        _SYSTEM_MAC = config.BRIDGE_ID
        return _SYSTEM_MAC
    
    try:
        # 2. FALLBACK: Use Hostname (Dynamic on HAOS!)
        host_id = socket.gethostname()
        
        if not host_id:
            host_id = "rtl-bridge-default"
            
        _SYSTEM_MAC = host_id
        return _SYSTEM_MAC

    except Exception:
        return "rtl-bridge-error-id"

def clean_mac(mac):
    """Cleans up MAC/ID string for use in topic/unique IDs."""
    # Removes special characters to make it MQTT-safe
    cleaned = re.sub(r'[^A-Za-z0-9]', '', str(mac))
    return cleaned.lower() if cleaned else "unknown"

def calculate_dew_point(temp_c, humidity):
    """Calculates Dew Point (F) using Magnus Formula."""
    if temp_c is None or humidity is None:
        return None
    if humidity <= 0:
        return None 
    try:
        b = 17.62
        c = 243.12
        gamma = (b * temp_c / (c + temp_c)) + math.log(humidity / 100.0)
        dp_c = (c * gamma) / (b - gamma)
        return round(dp_c * 1.8 + 32, 1) # Return Fahrenheit
    except Exception:
        return None

def validate_radio_config(radio_conf):
    """Analyze a radio configuration dictionary for common user errors.

    Returns a list of warning strings.

    This validator is intentionally best-effort: it should never raise and
    should not block startup.

    USB mode guidance:
      - If you run more than one RTL-SDR, strongly prefer setting a unique
        `id` (USB serial) per radio.

    TCP mode guidance (rtl_tcp):
      - If `tcp_host`/`tcp_port` is set OR `device` is an `rtl_tcp:HOST:PORT`
        selector, `id` is not required.
    """
    warnings = []

    def _is_tcp_selector(dev: str) -> bool:
        return dev.strip().lower().startswith("rtl_tcp:")

    def _safe_int(value, default=0):
        try:
            if value is None:
                return default
            if isinstance(value, bool):
                return int(value)
            s = str(value).strip()
            if s == "":
                return default
            return int(s)
        except Exception:
            return default

    # 1) Frequency suffix check (rtl_433 defaults to Hz if no suffix is present)
    freq_str = str(radio_conf.get("freq", ""))
    frequencies = [f.strip() for f in freq_str.split(",") if f.strip()]

    for f in frequencies:
        # pure number with no unit suffix
        if re.match(r"^\d+(\.\d+)?$", f):
            try:
                val = float(f)
            except Exception:
                continue
            # If value is < 1,000,000, it's almost certainly not Hz.
            if val < 1_000_000:
                warnings.append(
                    f"Frequency '{f}' has no suffix and will be read as Hz (impossible). "
                    f"Did you mean '{f}M'?"
                )

    # 2) Hop interval sanity (hopping requires >= 2 freqs)
    hop_raw = radio_conf.get("hop_interval", 0)
    hop = _safe_int(hop_raw, 0)
    if hop_raw not in (None, "", 0) and hop == 0:
        warnings.append(
            f"Hop interval '{hop_raw}' is not a valid integer; hopping will be disabled."
        )

    if hop > 0 and len(frequencies) < 2 and freq_str.strip():
        warnings.append(
            f"Hop interval is set to {hop}s, but only 1 frequency provided ({freq_str}). "
            "Hopping will be ignored."
        )

    # 3) Sample rate suffix check
    rate = str(radio_conf.get("rate", ""))
    if re.match(r"^\d+$", rate):
        try:
            val = int(rate)
        except Exception:
            val = 0
        if val and val < 1_000_000:
            warnings.append(
                f"Sample rate '{rate}' has no suffix (e.g. 'k'). "
                f"Did you mean '{rate}k'?"
            )

    # 4) Device selection / ID guidance
    # If user explicitly pins a device (USB selector, index, Soapy selector, or rtl_tcp),
    # `id` is not required.
    dev = str(radio_conf.get("device") or "").strip()
    tcp_host = str(radio_conf.get("tcp_host") or "").strip()
    tcp_port = radio_conf.get("tcp_port")
    r_id = radio_conf.get("id")

    is_tcp = bool(tcp_host) or _is_tcp_selector(dev)

    if _is_tcp_selector(dev):
        # Best-effort parse: rtl_tcp:HOST:PORT
        parts = dev.split(":", 2)
        if len(parts) < 3 or not parts[1].strip():
            warnings.append(
                f"Device selector '{dev}' looks like rtl_tcp but is missing HOST and/or PORT. "
                "Expected 'rtl_tcp:HOST:PORT'."
            )
        else:
            # PORT can be omitted in some rtl_tcp client implementations, but rtl_433 expects it.
            host = parts[1].strip()
            port_part = parts[2].strip() if len(parts) >= 3 else ""
            if host and port_part:
                if not port_part.isdigit():
                    warnings.append(
                        f"rtl_tcp port '{port_part}' is not numeric in device selector '{dev}'."
                    )

    if tcp_host and tcp_port not in (None, ""):
        # tcp_port is validated by add-on schema, but standalone JSON/env may bypass it.
        if _safe_int(tcp_port, 0) <= 0:
            warnings.append(
                f"tcp_port '{tcp_port}' is not a valid port; rtl_tcp will default to 1234."
            )

    if (r_id is None or str(r_id).strip() == "") and not dev and not is_tcp:
        warnings.append(
            "Configuration is missing a device 'id' (USB serial) or explicit 'device' selector. "
            "This radio may default to index 0 and conflict with others."
        )

    return warnings



def get_homeassistant_country_code() -> str | None:
    """Best-effort: infer Home Assistant country code (e.g. 'US', 'DE').

    - Add-on: reads /config/.storage/core.config
    - Standalone: optionally uses env var HOMEASSISTANT_COUNTRY / HA_COUNTRY
    Returns None if unknown.
    """
    # 1) Env override (works in any mode)
    for k in ("HOMEASSISTANT_COUNTRY", "HA_COUNTRY", "COUNTRY"):
        v = os.getenv(k)
        if v and str(v).strip():
            return str(v).strip().upper()

    # 2) Home Assistant storage (add-on)
    core_cfg = "/config/.storage/core.config"
    try:
        with open(core_cfg, "r", encoding="utf-8") as f:
            obj = json.load(f)
        # Typical structure: {"data": {"country": "US", ...}, ...}
        data = obj.get("data") if isinstance(obj, dict) else None
        if isinstance(data, dict):
            c = data.get("country")
            if c and str(c).strip():
                return str(c).strip().upper()
    except Exception:
        pass

    return None


_EU_868_COUNTRIES = {
    # EU + EEA + UK + CH (broadly 868 MHz ISM users)
    "AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
    "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE",
    "IS","LI","NO","CH","GB",
}


def choose_secondary_band_defaults(
    plan: str = "auto",
    country_code: str | None = None,
    secondary_override: str | None = None,
) -> tuple[str, int]:
    """Return (freq_str, hop_interval) for the secondary radio in auto multi-mode.

    plan:
      - 'auto' : infer using country_code; if unknown, hop 868+915
      - 'eu'   : 868M
      - 'us'   : 915M
      - 'world': hop 868M,915M
      - 'custom': use secondary_override (if provided), otherwise behave like 'auto'
      - otherwise: treated as custom freq string (e.g. '920M' or '868M,915M')
    """
    p = (plan or "auto").strip().lower()

    if p in ("custom",):
        ov = (secondary_override or "").strip()
        if ov:
            hop = 15 if "," in ov else 0
            return (ov, hop)
        # No override provided; fall back to auto behavior.
        p = "auto"

    if p in ("auto", "detect", "country"):
        cc = (country_code or "").strip().upper()
        if cc in _EU_868_COUNTRIES:
            return ("868M", 0)
        if cc:
            # Default non-EU to 915M. Users can override with plan/custom freq.
            return ("915M", 0)
        # Unknown country: be internationally tolerant by hopping both.
        return ("868M,915M", 15)

    if p in ("eu", "europe", "uk"):
        return ("868M", 0)

    if p in ("us", "usa", "na", "north_america", "north-america", "canada", "au", "australia", "nz", "new_zealand"):
        return ("915M", 0)

    if p in ("world", "global", "intl", "international"):
        return ("868M,915M", 15)

    # Treat anything else as a custom freq string.
    # If multiple freqs are provided, hop interval is enabled.
    freq_str = plan.strip()
    hop = 15 if "," in freq_str else 0
    return (freq_str, hop)


def choose_hopper_band_defaults(
    country_code: str | None = None,
    used_freqs: set[str] | None = None,
) -> str:
    """Return a comma-separated frequency string for the optional 3rd "hopper" radio.

    Goal:
      - Do NOT overlap with the primary/secondary radios (pass used_freqs to enforce this).
      - Be "interesting" (scan bands where people commonly have *other* stuff).

    Notes:
      - This is intentionally opportunistic and may miss bursts while tuned elsewhere.
      - The hopper is best-effort: if all candidates overlap with used_freqs, returns "".

    Candidate bands (ordered by "interesting" likelihood):
      - US/CA/AU/NZ/etc (typically already covering 433 + 915): 315, 345, 390, 868
      - EU/UK/EEA/CH   (typically already covering 433 + 868): 169.4, 915, 315, 345
        * 169.4 MHz is used for some metering in parts of Europe; needs an appropriate antenna.
    """

    cc = (country_code or "").strip().upper()
    u = {s.strip().lower() for s in (used_freqs or set()) if s.strip()}

    if cc and cc in _EU_868_COUNTRIES:
        candidates = ["169.4M", "868.95M", "869.525M", "915M"]
    else:
        candidates = ["315M", "345M", "390M", "868M"]

    chosen = [f for f in candidates if f.strip().lower() not in u]
    return ",".join(chosen)
