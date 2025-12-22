def test_main_manual_config_duplicate_ids_and_unconfigured_hardware(mocker, capsys):
    import main
    import config

    mocker.patch.object(main, "get_version", return_value="vtest")
    mocker.patch.object(main, "show_logo", lambda *_: None)
    mocker.patch.object(main, "check_dependencies", lambda: None)

    class DummyMQTT:
        def __init__(self, version=None):
            self.version = version
        def start(self): return
        def stop(self): return

    class DummyProcessor:
        def __init__(self, mqtt): self.mqtt = mqtt
        def start_throttle_loop(self): return

    class DummyThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon
        def start(self): return

    mocker.patch.object(main, "HomeNodeMQTT", DummyMQTT)
    mocker.patch.object(main, "DataProcessor", DummyProcessor)
    mocker.patch.object(main.threading, "Thread", DummyThread)
    mocker.patch.object(main, "system_stats_loop", lambda *a, **k: None)
    mocker.patch.object(main, "rtl_loop", lambda *a, **k: None)
    mocker.patch.object(main, "get_system_mac", return_value="aa:bb:cc:dd:ee:ff")
    mocker.patch.object(main, "validate_radio_config", return_value=[])

    # Two devices share same serial + one extra unconfigured device
    mocker.patch.object(
        main,
        "discover_rtl_devices",
        return_value=[
            {"name": "RTL0", "id": "ABC", "index": 0},
            {"name": "RTL1", "id": "ABC", "index": 1},
            {"name": "RTL2", "id": "EXTRA", "index": 2},
        ],
    )

    mocker.patch.object(
        config,
        "RTL_CONFIG",
        [
            {"name": "Radio1", "id": "ABC", "freq": "433.92M", "rate": "250k", "hop_interval": 0},
            {"name": "Dup", "id": "ABC", "freq": "433.92M", "rate": "250k", "hop_interval": 0},
            {"name": "Missing", "id": "NOPE", "freq": "433.92M", "rate": "250k", "hop_interval": 0},
        ],
    )
    mocker.patch.object(config, "RTL_DEFAULT_FREQ", "433.92M")
    mocker.patch.object(config, "RTL_DEFAULT_HOP_INTERVAL", 0)
    mocker.patch.object(config, "RTL_DEFAULT_RATE", "250k")
    mocker.patch.object(config, "BRIDGE_NAME", "Bridge")

    calls = {"n": 0}
    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] >= 7:
            raise KeyboardInterrupt()

    mocker.patch.object(main.time, "sleep", side_effect=fake_sleep)

    main.main()

    out = capsys.readouterr().out.lower()
    assert "multiple sdrs detected with same serial" in out
    assert "duplicate id 'abc'" in out
    assert "configured serial nope not found" in out
    assert "detected but not configured" in out  # triggered by EXTRA


def test_main_auto_mode_warns_when_ignoring_extra_radios(mocker, capsys):
    import main
    import config

    mocker.patch.object(main, "get_version", return_value="vtest")
    mocker.patch.object(main, "show_logo", lambda *_: None)
    mocker.patch.object(main, "check_dependencies", lambda: None)

    class DummyMQTT:
        def __init__(self, version=None): self.version = version
        def start(self): return
        def stop(self): return

    class DummyProcessor:
        def __init__(self, mqtt): self.mqtt = mqtt
        def start_throttle_loop(self): return

    class DummyThread:
        def __init__(self, target=None, args=(), daemon=None): pass
        def start(self): return

    mocker.patch.object(main, "HomeNodeMQTT", DummyMQTT)
    mocker.patch.object(main, "DataProcessor", DummyProcessor)
    mocker.patch.object(main.threading, "Thread", DummyThread)
    mocker.patch.object(main, "system_stats_loop", lambda *a, **k: None)
    mocker.patch.object(main, "rtl_loop", lambda *a, **k: None)
    mocker.patch.object(main, "get_system_mac", return_value="aa:bb:cc:dd:ee:ff")
    mocker.patch.object(main, "validate_radio_config", return_value=[])

    mocker.patch.object(
        main,
        "discover_rtl_devices",
        return_value=[
            {"name": "RTL0", "id": "S0", "index": 0},
            {"name": "RTL1", "id": "S1", "index": 1},
        ],
    )

    mocker.patch.object(config, "RTL_CONFIG", [])
    mocker.patch.object(config, "RTL_DEFAULT_FREQ", "433.92M,315M")
    mocker.patch.object(config, "RTL_DEFAULT_HOP_INTERVAL", 10)
    mocker.patch.object(config, "RTL_DEFAULT_RATE", "250k")
    mocker.patch.object(config, "BRIDGE_NAME", "Bridge")

    calls = {"n": 0}
    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] >= 4:
            raise KeyboardInterrupt()

    mocker.patch.object(main.time, "sleep", side_effect=fake_sleep)

    main.main()
    out = capsys.readouterr().out.lower()
    assert "ignored" in out
