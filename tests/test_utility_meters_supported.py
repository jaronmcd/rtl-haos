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


def _common_monkeypatch(monkeypatch):
    monkeypatch.setattr(mqtt_handler.mqtt, "Client", lambda *a, **k: DummyClient())
    monkeypatch.setattr(mqtt_handler, "clean_mac", lambda s: "deadbeef")
    monkeypatch.setattr(config, "ID_SUFFIX", "_T", raising=False)
    monkeypatch.setattr(config, "BRIDGE_NAME", "Bridge", raising=False)
    monkeypatch.setattr(config, "BRIDGE_ID", "bridgeid", raising=False)
    monkeypatch.setattr(config, "RTL_EXPIRE_AFTER", 60, raising=False)
    monkeypatch.setattr(config, "VERBOSE_TRANSMISSIONS", False, raising=False)


def test_badger_orion_volume_gal_discovery(monkeypatch):
    """Badger-ORION emits volume_gal; ensure we publish it as a water total."""
    _common_monkeypatch(monkeypatch)
    monkeypatch.setattr(config, "MAIN_SENSORS", ["volume_gal"], raising=False)

    h = mqtt_handler.HomeNodeMQTT(version="vtest")
    c = h.client

    h.send_sensor("device_x", "volume_gal", 12345, "Badger deadbeef", "Badger-ORION")

    cfg = _last_config_payload(c, "deadbeef_volume_gal_T")
    assert cfg.get("device_class") == "water"
    assert cfg.get("unit_of_measurement") == "gal"
    assert cfg.get("state_class") == "total_increasing"
    assert "entity_category" not in cfg  # not diagnostic

    st = _last_state_payload(c, "deadbeef", "volume_gal")
    assert st == "12345"


def test_neptune_r900_meter_reading_uses_gallons(monkeypatch):
    """Neptune-R900 is normalized to meter_reading and should be reported in gallons."""
    _common_monkeypatch(monkeypatch)
    monkeypatch.setattr(config, "MAIN_SENSORS", ["meter_reading"], raising=False)

    h = mqtt_handler.HomeNodeMQTT(version="vtest")
    c = h.client

    # 1) Reading arrives first (no commodity hint yet)
    h.send_sensor("device_x", "meter_reading", 100.0, "Neptune deadbeef", "Neptune-R900")
    cfg1 = _last_config_payload(c, "deadbeef_meter_reading_T")
    assert cfg1.get("unit_of_measurement") == "ft³"  # fallback before commodity is known

    # 2) Type arrives later; triggers refresh with gallons
    h.send_sensor("device_x", "type", "water", "Neptune deadbeef", "Neptune-R900")
    cfg2 = _last_config_payload(c, "deadbeef_meter_reading_T")
    assert cfg2.get("unit_of_measurement") == "gal"
    assert cfg2.get("device_class") == "water"


def test_ert_scm_electric_inference_updates_discovery(monkeypatch):
    """ERT-SCM can only be classified once ert_type arrives; ensure we update to energy."""
    _common_monkeypatch(monkeypatch)
    monkeypatch.setattr(config, "MAIN_SENSORS", ["consumption_data"], raising=False)

    h = mqtt_handler.HomeNodeMQTT(version="vtest")
    c = h.client

    # 1) consumption_data arrives first (ERT-SCM reports hundredths)
    h.send_sensor("device_x", "consumption_data", 2735618, "ERT deadbeef", "ERT-SCM")
    cfg1 = _last_config_payload(c, "deadbeef_consumption_data_T")
    assert cfg1.get("unit_of_measurement") == "ft³"  # default before ert_type
    st1 = _last_state_payload(c, "deadbeef", "consumption_data")
    assert st1 == "27356.18"

    # 2) ert_type arrives (7 = electric per rtlamr conventions)
    h.send_sensor("device_x", "ert_type", 7, "ERT deadbeef", "ERT-SCM")
    cfg2 = _last_config_payload(c, "deadbeef_consumption_data_T")
    assert cfg2.get("device_class") == "energy"
    assert cfg2.get("unit_of_measurement") == "kWh"
