def test_build_cmd_tcp_port_invalid_defaults_to_1234():
    import rtl_manager

    radio = {
        "name": "Remote SDR",
        "freq": "433.92M",
        "tcp_host": "192.168.1.10",
        "tcp_port": "notaport",
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    d_idx = cmd.index("-d") + 1
    assert cmd[d_idx] == "rtl_tcp:192.168.1.10:1234"


def test_build_cmd_tcp_port_zero_defaults_to_1234():
    import rtl_manager

    radio = {
        "name": "Remote SDR",
        "freq": "433.92M",
        "tcp_host": "192.168.1.10",
        "tcp_port": 0,
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    d_idx = cmd.index("-d") + 1
    assert cmd[d_idx] == "rtl_tcp:192.168.1.10:1234"
