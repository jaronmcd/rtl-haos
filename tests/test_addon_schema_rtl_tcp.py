def test_addon_config_schema_includes_tcp_fields():
    with open("config.yaml", "r", encoding="utf-8") as f:
        text = f.read()

    assert "tcp_host:" in text
    assert "tcp_port:" in text
