"""Callback error-path tests for HomeNodeMQTT."""

import json
import threading
from unittest import mock

from mqtt_handler import HomeNodeMQTT


class TestCallbackErrorPaths:
    def test_on_message_malformed_json_does_not_raise(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()
        msg = mock.MagicMock(topic="x/y", payload=b"{bad json")

        h._on_message(mock.MagicMock(), None, msg)

    def test_on_message_none_msg_raises_attribute_error(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()
        try:
            h._on_message(mock.MagicMock(), None, None)
            assert False, "Expected AttributeError"
        except AttributeError:
            pass

    def test_on_disconnect_enqueues_worker_op(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()
        spy = mocker.patch.object(h, "_enqueue_worker_op", return_value=True)

        h._on_disconnect(mock.MagicMock(), None, 0)

        assert spy.called
        first = spy.call_args.args[0]
        assert first["op"] == "on_disconnect"

    def test_on_connect_success_inline_path(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()
        mocker.patch.object(h, "_enqueue_worker_op", return_value=False)
        impl = mocker.patch.object(h, "_on_connect_success_impl")

        h._on_connect(mock.MagicMock(), None, None, 0)

        impl.assert_called_once()

    def test_on_connect_failure_sets_disconnected(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()
        h._mqtt_connected = True

        h._on_connect(mock.MagicMock(), None, None, 5)

        assert h._mqtt_connected is False

    def test_on_message_impl_nuking_with_invalid_payload_safe(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()
        h.is_nuking = True
        h.nuke_command_topic = "nuke"
        h.restart_command_topic = "restart"

        h._on_message_impl(mock.MagicMock(), None, "homeassistant/sensor/test/state", b"not-json")

    def test_concurrent_on_message_calls_safe(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()
        h.nuke_command_topic = "nuke"
        h.restart_command_topic = "restart"
        errors = []

        def worker(i):
            try:
                payload = b"bad" if i % 2 == 0 else json.dumps({"ok": i}).encode()
                msg = mock.MagicMock(topic=f"t/{i}", payload=payload)
                h._on_message(mock.MagicMock(), None, msg)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        assert not errors
