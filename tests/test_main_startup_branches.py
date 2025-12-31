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
    
    # --- UPDATED ASSERTIONS FOR NEW BEHAVIOR ---
    # Old behavior: assert "multiple sdrs detected with same serial" in out
    # New behavior: The duplicates are renamed, so the warning is gone.
    assert "renamed duplicate serial 'abc' to 'abc-1'" in out
    
    # The CONFIG still has duplicates, so this error should still appear:
    assert "duplicate id 'abc'" in out 
    
    # "Missing" radio logic remains the same
    assert "configured serial nope not found" in out
    
    # "EXTRA" logic remains the same
    assert "detected but not configured" in out


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
    assert "auto multi-radio enabled" in out
    assert "radio #2" in out

def test_main_deduplicates_hardware_serials(mocker, capsys):
    """
    New test case: Verify that if discover_rtl_devices returns duplicates,
    main.py renames them before processing the hardware map.
    """
    import main
    import config

    # --- Mocks ---
    mocker.patch.object(main, "get_version", return_value="vtest")
    mocker.patch.object(main, "show_logo", lambda *_: None)
    mocker.patch.object(main, "check_dependencies", lambda: None)
    mocker.patch.object(main, "get_system_mac", return_value="aa:bb:cc:dd:ee:ff")
    
    class DummyMQTT:
        def __init__(self, version=None): self.version = version
        def start(self): return
        def stop(self): return

    class DummyProcessor:
        def __init__(self, mqtt): self.mqtt = mqtt
        def start_throttle_loop(self): return

    mocker.patch.object(main, "HomeNodeMQTT", DummyMQTT)
    mocker.patch.object(main, "DataProcessor", DummyProcessor)
    mocker.patch.object(main, "system_stats_loop", lambda *a, **k: None)
    mocker.patch.object(main, "rtl_loop", lambda *a, **k: None)
    
    # --- The Core Scenario: 2 Devices, Same Serial ---
    mocker.patch.object(
        main,
        "discover_rtl_devices",
        return_value=[
            {"name": "RTL_00000001", "id": "00000001", "index": 0},
            {"name": "RTL_00000001", "id": "00000001", "index": 1}, # Duplicate!
        ],
    )
    
    mocker.patch.object(config, "RTL_CONFIG", None)
    
    # --- FIX: Increase sleep count to survive startup ---
    # 1. Logo
    # 2. Radio 1 Start
    # 3. Radio 2 Start
    # 4. Main Loop (We want to interrupt HERE)
    calls = {"n": 0}
    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] >= 4: raise KeyboardInterrupt()
    mocker.patch.object(main.time, "sleep", side_effect=fake_sleep)

    # --- Run ---
    main.main()

    # --- Verify ---
    out = capsys.readouterr().out
    
    # 1. Check for the specific "Renamed" log message
    assert "Renamed duplicate Serial '00000001' to '00000001-1'" in out
    
    # 2. Verify the hardware map contains BOTH keys
    assert "'00000001': 0" in out
    assert "'00000001-1': 1" in out