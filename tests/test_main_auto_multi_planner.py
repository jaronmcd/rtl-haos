import builtins
import copy
import importlib

import pytest


class DummyMQTT:
    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class DummyProcessor:
    def __init__(self, mqtt_handler):
        self.mqtt_handler = mqtt_handler

    def start_throttle_loop(self):
        # no-op for tests
        return


class FakeThread:
    """
    Replaces threading.Thread so main() doesn't actually spawn background threads.
    For rtl_loop/system_stats_loop we call target synchronously.
    """
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon

    def start(self):
        if self.target:
            return self.target(*self.args, **self.kwargs)
        return None


def _import_main_and_restore_print():
    """
    main.py overwrites builtins.print at import-time for colorful logging.
    For tests, restore it so pytest output/capture behaves normally.
    """
    main = importlib.import_module("main")
    # Restore print
    if hasattr(main, "_original_print"):
        builtins.print = main._original_print
    return main


def run_main(
    monkeypatch,
    *,
    detected_devices,
    rtl_config=None,
    auto_multi=True,
    auto_max_radios=0,
    auto_hard_cap=3,
    country="US",
    band_plan="auto",
    secondary_defaults=("915M", 0),
    hopper_defaults="315M,345M,390M,868M",
    secondary_override="",
    hopper_override="",
):
    """
    Executes main.main() once with heavy monkeypatching; returns list of radio dicts
    passed to rtl_loop in startup order.
    """
    main = _import_main_and_restore_print()

    # Prevent external deps / delays
    monkeypatch.setattr(main, "check_dependencies", lambda: None)
    monkeypatch.setattr(main, "get_version", lambda: "vtest")
    monkeypatch.setattr(main, "show_logo", lambda *_: None)

    # Sleep: ignore startup sleeps, but exit loop quickly
    sleep_calls = {"n": 0}
    def fake_sleep(seconds):
        # Allow the startup sleeps to be skipped; exit the main loop on the first 1s sleep.
        if seconds == 1:
            raise KeyboardInterrupt()
        return None
    monkeypatch.setattr(main.time, "sleep", fake_sleep)

    # Replace threading
    monkeypatch.setattr(main.threading, "Thread", FakeThread)

    # Replace MQTT + processor
    monkeypatch.setattr(main, "HomeNodeMQTT", DummyMQTT)
    monkeypatch.setattr(main, "DataProcessor", DummyProcessor)

    # Replace monitors/validation
    monkeypatch.setattr(main, "system_stats_loop", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "validate_radio_config", lambda *_args, **_kwargs: [])

    # Fake hardware discovery
    monkeypatch.setattr(main, "discover_rtl_devices", lambda: detected_devices)

    # Country + band selection
    monkeypatch.setattr(main, "get_homeassistant_country_code", lambda: country)

    def fake_choose_secondary_band_defaults(plan, country_code, secondary_override):
        return secondary_defaults
    monkeypatch.setattr(main, "choose_secondary_band_defaults", fake_choose_secondary_band_defaults)

    def fake_choose_hopper_band_defaults(country_code, used_freqs):
        return hopper_defaults
    monkeypatch.setattr(main, "choose_hopper_band_defaults", fake_choose_hopper_band_defaults)

    # Patch config values
    cfg = main.config
    monkeypatch.setattr(cfg, "BRIDGE_NAME", "RTL-HAOS", raising=False)
    monkeypatch.setattr(cfg, "RTL_DEFAULT_FREQ", "433.92M", raising=False)
    monkeypatch.setattr(cfg, "RTL_DEFAULT_RATE", "250k", raising=False)
    monkeypatch.setattr(cfg, "RTL_DEFAULT_HOP_INTERVAL", 0, raising=False)

    monkeypatch.setattr(cfg, "RTL_CONFIG", rtl_config, raising=False)
    monkeypatch.setattr(cfg, "RTL_AUTO_MULTI", auto_multi, raising=False)
    monkeypatch.setattr(cfg, "RTL_AUTO_MAX_RADIOS", auto_max_radios, raising=False)
    monkeypatch.setattr(cfg, "RTL_AUTO_HARD_CAP", auto_hard_cap, raising=False)
    monkeypatch.setattr(cfg, "RTL_AUTO_BAND_PLAN", band_plan, raising=False)
    monkeypatch.setattr(cfg, "RTL_AUTO_SECONDARY_FREQ", secondary_override, raising=False)
    monkeypatch.setattr(cfg, "RTL_AUTO_HOPPER_FREQS", hopper_override, raising=False)

    # capture rtl_loop calls
    started = []
    def fake_rtl_loop(radio, *_args, **_kwargs):
        started.append(copy.deepcopy(radio))
        return
    monkeypatch.setattr(main, "rtl_loop", fake_rtl_loop)

    # run
    main.main()

    return started


def _mk_device(serial, index, name=None):
    d = {"id": str(serial), "index": index}
    if name:
        d["name"] = name
    else:
        d["name"] = f"RTL_{serial}"
    return d


def test_auto_single_starts_primary_only(monkeypatch):
    radios = run_main(
        monkeypatch,
        detected_devices=[_mk_device("101", 0)],
        rtl_config=[],
        auto_multi=False,
    )
    assert len(radios) == 1
    r0 = radios[0]
    assert r0["slot"] == 0
    assert r0["freq"] == "433.92M"
    assert r0["rate"] == "250k"
    assert r0["hop_interval"] == 0
    assert r0["index"] == 0


def test_auto_multi_two_radios_us_secondary_915(monkeypatch):
    radios = run_main(
        monkeypatch,
        detected_devices=[_mk_device("101", 0), _mk_device("102", 1)],
        rtl_config=[],
        auto_multi=True,
        country="US",
        secondary_defaults=("915M", 0),
    )
    assert len(radios) == 2
    assert radios[0]["freq"] == "433.92M"
    assert radios[1]["freq"] == "915M"
    assert radios[1]["hop_interval"] == 0
    assert radios[1]["rate"] == "1024k"


def test_auto_multi_three_radios_us_third_is_hopper_no_overlap(monkeypatch):
    radios = run_main(
        monkeypatch,
        detected_devices=[_mk_device("101", 0), _mk_device("102", 1), _mk_device("103", 2)],
        rtl_config=[],
        auto_multi=True,
        auto_max_radios=3,
        country="US",
        secondary_defaults=("915M", 0),
        hopper_defaults="315M,345M,390M,868M",
    )
    assert len(radios) == 3
    assert radios[0]["freq"] == "433.92M"
    assert radios[1]["freq"] == "915M"

    hopper = radios[2]["freq"]
    # Must not overlap exact primary/secondary freqs
    assert "433.92M" not in hopper
    assert "915M" not in hopper
    # Should still contain something "interesting"
    assert hopper in ("315M,345M,390M,868M", "315M,345M,390M,868M".replace(" ", ""))


def test_auto_multi_three_radios_splits_secondary_multifreq(monkeypatch):
    radios = run_main(
        monkeypatch,
        detected_devices=[_mk_device("101", 0), _mk_device("102", 1), _mk_device("103", 2)],
        rtl_config=[],
        auto_multi=True,
        auto_max_radios=3,
        country=None,
        secondary_defaults=("868M,915M", 15),
        hopper_defaults="315M,345M",
    )
    # split should produce 3 radios: primary + 868 + 915 (no hopping)
    assert len(radios) == 3
    assert radios[1]["freq"] == "868M"
    assert radios[1]["hop_interval"] == 0
    assert radios[2]["freq"] == "915M"
    assert radios[2]["hop_interval"] == 0


def test_auto_multi_unknown_country_hops_when_only_two(monkeypatch):
    radios = run_main(
        monkeypatch,
        detected_devices=[_mk_device("101", 0), _mk_device("102", 1)],
        rtl_config=[],
        auto_multi=True,
        auto_max_radios=2,
        country=None,
        secondary_defaults=("868M,915M", 0),
    )
    assert len(radios) == 2
    assert radios[1]["freq"] == "868M,915M"
    # if multi-freq secondary and only 2 radios: hop should default to 15s
    assert radios[1]["hop_interval"] == 15


def test_auto_multi_skips_third_if_only_overlap(monkeypatch):
    # Force hopper defaults to overlap secondary so it gets filtered to empty.
    radios = run_main(
        monkeypatch,
        detected_devices=[_mk_device("101", 0), _mk_device("102", 1), _mk_device("103", 2)],
        rtl_config=[],
        auto_multi=True,
        auto_max_radios=3,
        country="US",
        secondary_defaults=("915M", 0),
        hopper_defaults="915M",
    )
    # Should skip Radio #3 entirely
    assert len(radios) == 2
    assert radios[0]["freq"] == "433.92M"
    assert radios[1]["freq"] == "915M"


def test_manual_config_maps_serial_to_index(monkeypatch):
    detected = [_mk_device("101", 0), _mk_device("102", 1)]
    rtl_config = [
        {"name": "PrimaryManual", "id": "102", "freq": "915M", "rate": "1024k", "hop_interval": 0},
    ]
    radios = run_main(
        monkeypatch,
        detected_devices=detected,
        rtl_config=rtl_config,
        auto_multi=True,  # should not matter
        country="US",
    )
    assert len(radios) == 1
    assert radios[0]["id"] == "102"
    assert radios[0]["index"] == 1  # mapped from scan
    assert radios[0]["freq"] == "915M"


def test_manual_config_duplicate_ids_skips_second(monkeypatch):
    detected = [_mk_device("101", 0), _mk_device("102", 1)]
    rtl_config = [
        {"name": "R1", "id": "101", "freq": "433.92M", "rate": "250k", "hop_interval": 0},
        {"name": "R2", "id": "101", "freq": "915M", "rate": "1024k", "hop_interval": 0},
    ]
    radios = run_main(
        monkeypatch,
        detected_devices=detected,
        rtl_config=rtl_config,
        auto_multi=True,
        country="US",
    )
    assert len(radios) == 1
    assert radios[0]["id"] == "101"
    assert radios[0]["index"] == 0


def test_auto_multi_detected_count_respects_hard_cap(monkeypatch):
    detected = [_mk_device("101", 0), _mk_device("102", 1), _mk_device("103", 2), _mk_device("104", 3)]
    radios = run_main(
        monkeypatch,
        detected_devices=detected,
        rtl_config=[],
        auto_multi=True,
        auto_max_radios=0,  # detected count
        auto_hard_cap=3,
        country="US",
        secondary_defaults=("915M", 0),
    )
    # capped to 3
    assert len(radios) == 3
