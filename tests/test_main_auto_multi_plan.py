import builtins

import pytest

# main.py overrides builtins.print for colored/timestamped logs.
# Import it, then immediately restore the original print so other tests
# that assert on log strings aren't affected.
_ORIG_PRINT = builtins.print
import main as main_mod
builtins.print = _ORIG_PRINT


class FakeThread:
    created = []

    def __init__(self, target=None, args=(), daemon=None, **kwargs):
        self.target = target
        self.args = args
        self.daemon = daemon
        FakeThread.created.append(self)

    def start(self):
        # Do not actually run anything in tests.
        return None


class DummyMQTT:
    def __init__(self, version=None):
        self.version = version

    def start(self):
        return None

    def stop(self):
        return None


class DummyProcessor:
    def __init__(self, mqtt_handler):
        self.mqtt_handler = mqtt_handler

    def start_throttle_loop(self):
        return None


def _setup_main_for_test(monkeypatch, detected_devices, country_code):
    FakeThread.created.clear()

    # Avoid launching any real threads or external deps.
    monkeypatch.setattr(main_mod, "check_dependencies", lambda: None)
    monkeypatch.setattr(main_mod, "show_logo", lambda *_: None)
    monkeypatch.setattr(main_mod, "get_version", lambda: "vtest")

    monkeypatch.setattr(main_mod, "HomeNodeMQTT", DummyMQTT)
    monkeypatch.setattr(main_mod, "DataProcessor", DummyProcessor)

    monkeypatch.setattr(main_mod.threading, "Thread", FakeThread)

    monkeypatch.setattr(main_mod, "discover_rtl_devices", lambda: detected_devices)
    monkeypatch.setattr(main_mod, "get_system_mac", lambda: "aa:bb:cc:dd:ee:ff")
    monkeypatch.setattr(main_mod, "get_homeassistant_country_code", lambda: country_code)

    # Force auto mode: rtl_config empty
    monkeypatch.setattr(main_mod.config, "RTL_CONFIG", [])

    # Stable defaults for assertions
    monkeypatch.setattr(main_mod.config, "RTL_DEFAULT_FREQ", "433.92M")
    monkeypatch.setattr(main_mod.config, "RTL_DEFAULT_HOP_INTERVAL", 60)
    monkeypatch.setattr(main_mod.config, "RTL_DEFAULT_RATE", "250k")

    monkeypatch.setattr(main_mod.config, "RTL_AUTO_MULTI", True)
    monkeypatch.setattr(main_mod.config, "RTL_AUTO_MAX_RADIOS", 0)
    monkeypatch.setattr(main_mod.config, "RTL_AUTO_HARD_CAP", 3)

    monkeypatch.setattr(main_mod.config, "RTL_AUTO_BAND_PLAN", "auto")
    monkeypatch.setattr(main_mod.config, "RTL_AUTO_SECONDARY_FREQ", "")
    monkeypatch.setattr(main_mod.config, "RTL_AUTO_PRIMARY_RATE", "250k")
    monkeypatch.setattr(main_mod.config, "RTL_AUTO_SECONDARY_RATE", "1024k")

    monkeypatch.setattr(main_mod.config, "RTL_AUTO_HOPPER_FREQS", "")
    monkeypatch.setattr(main_mod.config, "RTL_AUTO_HOPPER_HOP_INTERVAL", 20)
    monkeypatch.setattr(main_mod.config, "RTL_AUTO_HOPPER_RATE", "1024k")

    # Exit the infinite loop quickly (it sleeps(1) in the main loop)
    def fake_sleep(seconds):
        if seconds == 1:
            raise KeyboardInterrupt()
        return None

    monkeypatch.setattr(main_mod.time, "sleep", fake_sleep)



def _rtl_threads():
    return [t for t in FakeThread.created if t.target == main_mod.rtl_loop]


def test_auto_multi_three_radios_us_hopper_no_overlap(monkeypatch):
    detected = [
        {"index": 0, "id": "102", "name": "RTL_102"},
        {"index": 1, "id": "103", "name": "RTL_103"},
        {"index": 2, "id": "101", "name": "RTL_101"},
    ]

    _setup_main_for_test(monkeypatch, detected_devices=detected, country_code="US")

    # Run main() until our fake_sleep triggers KeyboardInterrupt.
    main_mod.main()

    threads = _rtl_threads()
    assert len(threads) == 3

    radios = [t.args[0] for t in threads]
    radios_by_slot = {r.get("slot"): r for r in radios}

    r1 = radios_by_slot[0]
    r2 = radios_by_slot[1]
    r3 = radios_by_slot[2]

    assert r1["freq"] == "433.92M"
    assert r1["rate"] == "250k"

    assert r2["freq"] == "915M"
    assert r2["rate"] == "1024k"

    # Hopper should not overlap the primary/secondary bands.
    used = {"433.92m", "915m"}
    hopper_parts = {p.strip().lower() for p in str(r3["freq"]).split(",") if p.strip()}
    assert not (hopper_parts & used)
    assert r3["hop_interval"] == 20


def test_auto_multi_three_radios_unknown_country_splits_868_915(monkeypatch):
    detected = [
        {"index": 0, "id": "201", "name": "RTL_201"},
        {"index": 1, "id": "202", "name": "RTL_202"},
        {"index": 2, "id": "203", "name": "RTL_203"},
    ]

    _setup_main_for_test(monkeypatch, detected_devices=detected, country_code=None)

    main_mod.main()

    threads = _rtl_threads()
    assert len(threads) == 3

    radios = [t.args[0] for t in threads]
    radios_by_slot = {r.get("slot"): r for r in radios}

    assert radios_by_slot[0]["freq"] == "433.92M"

    # Unknown country -> secondary is 868M,915M but we split across #2/#3 to avoid hopping
    assert radios_by_slot[1]["freq"] == "868M"
    assert radios_by_slot[1]["hop_interval"] == 0

    assert radios_by_slot[2]["freq"] == "915M"
    assert radios_by_slot[2]["hop_interval"] == 0


