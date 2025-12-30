import json

import pytest

import mqtt_handler
import config


class DummyClient:
    def __init__(self, *a, **k):
        self.published = []

    def username_pw_set(self, *_a, **_k):
        pass

    def will_set(self, *_a, **_k):
        pass

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def subscribe(self, *_a, **_k):
        pass


def _last_config_payload(client: DummyClient, unique_id_with_suffix: str):
    topic = f"homeassistant/sensor/{unique_id_with_suffix}/config"
    matches = [p for (t, p, _r) in client.published if t == topic]
    assert matches, f"Expected at least one config publish to {topic}"
    return json.loads(matches[-1])


def _last_state_payload(client: DummyClient, clean_id: str, field: str):
    topic = f"home/rtl_devices/{clean_id}/{field}"
    matches = [p for (t, p, _r) in client.published if t == topic]
    assert matches, f"Expected at least one state publish to {topic}"
    return matches[-1]


def test_scmplus_ccf_updates_after_metertype(monkeypatch):
    """If MeterType arrives after Consumption, we should update config + state to CCF."""
    # Use dummy client
    monkeypatch.setattr(mqtt_handler.mqtt, "Client", lambda *a, **k: DummyClient())

    # Deterministic IDs
    monkeypatch.setattr(mqtt_handler, "clean_mac", lambda s: "deadbeef")

    # Keep config deterministic
    monkeypatch.setattr(config, "ID_SUFFIX", "_T", raising=False)
    monkeypatch.setattr(config, "BRIDGE_NAME", "Bridge", raising=False)
    monkeypatch.setattr(config, "BRIDGE_ID", "bridgeid", raising=False)
    monkeypatch.setattr(config, "RTL_EXPIRE_AFTER", 60, raising=False)
    monkeypatch.setattr(config, "MAIN_SENSORS", ["Consumption"], raising=False)
    monkeypatch.setattr(config, "VERBOSE_TRANSMISSIONS", False, raising=False)

    # Enable CCF
    monkeypatch.setattr(config, "GAS_VOLUME_UNIT", "ccf", raising=False)

    h = mqtt_handler.HomeNodeMQTT(version="vtest")
    c = h.client

    # 1) Consumption arrives first (SCMplus Consumption is raw ft³)
    h.send_sensor("device_x", "Consumption", 217504, "SCMplus deadbeef", "SCMplus")

    # Initial config uses default ft³ from FIELD_META
    cfg1 = _last_config_payload(c, "deadbeef_Consumption_T")
    assert cfg1.get("unit_of_measurement") == "ft³"

    # Initial state (normalized to ft³)
    st1 = _last_state_payload(c, "deadbeef", "Consumption")
    assert st1 == "217504"

    # 2) MeterType arrives later, triggers refresh of utility entities
    h.send_sensor("device_x", "MeterType", "Gas", "SCMplus deadbeef", "SCMplus")

    # Config should now be updated to CCF
    cfg2 = _last_config_payload(c, "deadbeef_Consumption_T")
    assert cfg2.get("unit_of_measurement") == "CCF"
    assert cfg2.get("device_class") == "gas"

    # State should be re-published converted to CCF (ft³ / 100)
    st2 = _last_state_payload(c, "deadbeef", "Consumption")
    assert st2 == "2175.04"
