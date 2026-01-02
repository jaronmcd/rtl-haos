# tests/test_main.py
import builtins
import importlib
import io
import sys
import pytest


_ORIG_PRINT = builtins.print


def import_main_safely():
    """
    main.py patches builtins.print at import time.
    For unit tests, we import it, then immediately restore builtins.print so it
    doesn't affect other test modules.
    """
    sys.modules.pop("main", None)
    builtins.print = _ORIG_PRINT
    m = importlib.import_module("main")

    # Undo the import-time print hook side effect
    builtins.print = _ORIG_PRINT
    if hasattr(m, "_original_print"):
        m._original_print = _ORIG_PRINT
    return m


def test_get_version_parses_config_yaml(mocker, monkeypatch):
    main = import_main_safely()

    # Ensure no build metadata is appended for this test
    monkeypatch.delenv("RTL_HAOS_BUILD", raising=False)
    monkeypatch.delenv("RTL_HAOS_TWEAK", raising=False)
    mocker.patch("builtins.open", return_value=io.StringIO('name: X\nversion: "9.9.9"\n'))

    assert main.get_version() == "v9.9.9"


def test_get_version_appends_build_metadata(mocker, monkeypatch):
    main = import_main_safely()

    monkeypatch.setenv("RTL_HAOS_BUILD", "dev build")
    mocker.patch("builtins.open", return_value=io.StringIO('name: X\nversion: "9.9.9"\n'))

    # Space in build should be sanitized to a dash
    assert main.get_version() == "v9.9.9+dev-build"


def test_check_dependencies_missing_rtl_433_exits(mocker):
    main = import_main_safely()

    mocker.patch("subprocess.run", return_value=mocker.Mock(stdout=b""))
    # paho spec doesn't matter if rtl_433 missing first
    mocker.patch("importlib.util.find_spec", return_value=object())

    with pytest.raises(SystemExit):
        main.check_dependencies()


def test_check_dependencies_missing_paho_exits(mocker):
    main = import_main_safely()

    mocker.patch("subprocess.run", return_value=mocker.Mock(stdout=b"/usr/bin/rtl_433\n"))
    mocker.patch("importlib.util.find_spec", return_value=None)

    with pytest.raises(SystemExit):
        main.check_dependencies()


def test_main_smoke_run_exits_cleanly(mocker):
    # OPTIONAL but makes this test not require rtl_433 installed:
    mocker.patch("subprocess.run", return_value=mocker.Mock(stdout=b"/usr/bin/rtl_433\n"))
    mocker.patch("importlib.util.find_spec", return_value=object())

    main = import_main_safely()

    # Avoid real dependency checks / banner delay
    mocker.patch.object(main, "check_dependencies", lambda: None)
    mocker.patch.object(main, "show_logo", lambda *_: None)

    class DummyMQTT:
        def __init__(self, version=None):
            self.version = version
        def start(self): pass
        def stop(self): pass

    class DummyProcessor:
        def __init__(self, mqtt): self.mqtt = mqtt
        def start_throttle_loop(self): return

    class DummyThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target = target
            self.args = args
        def start(self): return

    # ✅ Patch what main.py actually calls (because of "from X import Y")
    mocker.patch.object(main, "HomeNodeMQTT", DummyMQTT)
    mocker.patch.object(main, "DataProcessor", DummyProcessor)
    mocker.patch.object(main, "discover_rtl_devices", return_value=[{"name": "RTL0", "id": "000", "index": 0}])
    mocker.patch.object(main, "rtl_loop", lambda *a, **k: None)
    mocker.patch.object(main, "system_stats_loop", lambda *a, **k: None)
    mocker.patch.object(main, "get_system_mac", return_value="aa:bb:cc:dd:ee:ff")
    mocker.patch.object(main, "validate_radio_config", return_value=[])

    # Patch config via the exact config object main imported
    mocker.patch.object(main.config, "RTL_CONFIG", [])
    mocker.patch.object(main.config, "RTL_DEFAULT_FREQ", "433.92M")
    mocker.patch.object(main.config, "RTL_DEFAULT_HOP_INTERVAL", 0)
    mocker.patch.object(main.config, "RTL_DEFAULT_RATE", "250k")
    mocker.patch.object(main.config, "BRIDGE_NAME", "Bridge")

    # Break the infinite loop in main
    calls = {"n": 0}
    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt()

    mocker.patch.object(main.time, "sleep", side_effect=fake_sleep)
    mocker.patch.object(main.threading, "Thread", DummyThread)

    main.main()

