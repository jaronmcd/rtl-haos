"""Cross-thread integration tests for refactored components."""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest import mock

import config
from data_processor import DataProcessor
from device_count import DeviceCountChannel
from mqtt_handler import HomeNodeMQTT


def _mk_manager():
    mgr = mock.MagicMock()
    mgr.should_process_frame.return_value = True
    mgr.add_or_update_device.return_value = None
    return mgr


class TestDataProcessorToMqtt:
    def test_immediate_dispatch_reaches_mqtt_send_sensor(self, mocker):
        mocker.patch.object(config, "RTL_THROTTLE_INTERVAL", 0)
        mqtt = mock.MagicMock()
        mqtt.send_sensor.return_value = {"topics": []}
        dp = DataProcessor(mqtt, None)

        dp.dispatch_reading("device_1", "temperature", 25.5, "Device 1", "ModelX")

        mqtt.send_sensor.assert_called_once()

    def test_concurrent_immediate_dispatch(self, mocker):
        mocker.patch.object(config, "RTL_THROTTLE_INTERVAL", 0)
        mqtt = mock.MagicMock()
        mqtt.send_sensor.return_value = {"topics": []}
        dp = DataProcessor(mqtt, None)

        def worker(tid):
            for i in range(30):
                dp.dispatch_reading(f"dev_{tid}", "temp", i, "Dev", "Model")

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(worker, i) for i in range(5)]
            for f in as_completed(futures):
                f.result()

        assert mqtt.send_sensor.call_count == 150

    def test_buffered_dispatch_under_concurrency(self, mocker):
        mocker.patch.object(config, "RTL_THROTTLE_INTERVAL", 10)
        dp = DataProcessor(mock.MagicMock(), _mk_manager())

        def worker(tid):
            for i in range(40):
                dp.dispatch_reading(f"dev_{tid % 3}", "hum", i, "Dev", "Model")

        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = [ex.submit(worker, i) for i in range(6)]
            for f in as_completed(futures):
                f.result()

        assert len(dp.buffer) > 0


class TestDeviceCountChannelIntegration:
    def test_device_count_push_updates_latest(self):
        ch = DeviceCountChannel(mock.MagicMock())

        ch.push(1)
        ch.push(2)
        ch.push(7)

        assert ch._count_last == 7
        assert ch._count_pending is True

    def test_start_thread_spawns_daemon_loop(self):
        ch = DeviceCountChannel(mock.MagicMock())
        t = ch.start_thread("abc", "Model", thread_factory=threading.Thread)

        assert t.daemon is True
        assert t.name == "device_count_loop"


class TestMqttThreadStateIntegration:
    def test_state_lock_and_publish_queue_initialized(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()

        assert hasattr(h, "_state_lock")
        assert hasattr(h, "_publish_queue")

    def test_send_sensor_async_multi_thread_queueing(self, mocker):
        mocker.patch("mqtt_handler.mqtt.Client")
        h = HomeNodeMQTT()
        h.start()

        try:
            results = []
            lock = threading.Lock()

            def worker(i):
                r = h.send_sensor_async(
                    sensor_id=f"dev{i}",
                    field="temp",
                    value=i,
                    device_name="Dev",
                    device_model="Model",
                    is_rtl=True,
                )
                with lock:
                    results.append(r)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=3.0)

            assert len(results) == 20
            assert all("accepted" in r for r in results)
        finally:
            h.stop()
