"""Concurrency tests for DataProcessor dispatch paths."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest import mock

import config
from data_processor import DataProcessor


def _mk_manager():
    mgr = mock.MagicMock()
    mgr.should_process_frame.return_value = True
    mgr.add_or_update_device.return_value = None
    return mgr


def _dispatch(dp, dev, field, value):
    dp.dispatch_reading(dev, field, value, "Dev", "Model")


class TestDataProcessorConcurrency:
    def test_buffered_dispatch_single_device_multithread(self, mocker):
        mocker.patch.object(config, "RTL_THROTTLE_INTERVAL", 10)
        dp = DataProcessor(mock.MagicMock(), _mk_manager())
        errors = []

        def worker(tid):
            try:
                for i in range(50):
                    _dispatch(dp, "device_1", f"f{tid}", i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        assert not errors
        assert "device_1" in dp.buffer
        assert "__meta__" in dp.buffer["device_1"]

    def test_buffered_dispatch_multi_device_multithread(self, mocker):
        mocker.patch.object(config, "RTL_THROTTLE_INTERVAL", 10)
        dp = DataProcessor(mock.MagicMock(), _mk_manager())

        def worker(tid):
            for i in range(40):
                _dispatch(dp, f"dev_{(tid + i) % 10}", "temp", i)

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(worker, i) for i in range(8)]
            for f in as_completed(futures):
                f.result()

        assert len(dp.buffer) > 0
        assert len(dp.buffer) <= 10

    def test_no_deadlock_under_contention(self, mocker):
        mocker.patch.object(config, "RTL_THROTTLE_INTERVAL", 10)
        dp = DataProcessor(mock.MagicMock(), _mk_manager())

        def worker(tid):
            for i in range(120):
                _dispatch(dp, f"dev_{tid}", "x", i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()

        start = time.time()
        for t in threads:
            t.join(timeout=5.0)
            assert not t.is_alive()
        assert time.time() - start < 5.0

    def test_immediate_dispatch_concurrent_calls(self, mocker):
        mocker.patch.object(config, "RTL_THROTTLE_INTERVAL", 0)
        mqtt = mock.MagicMock()
        mqtt.send_sensor.return_value = {"topics": []}
        dp = DataProcessor(mqtt, None)

        def worker(tid):
            for i in range(50):
                _dispatch(dp, f"dev_{tid}", "temp", i)

        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = [ex.submit(worker, i) for i in range(6)]
            for f in as_completed(futures):
                f.result()

        assert mqtt.send_sensor.call_count == 300

    def test_none_values_are_ignored(self, mocker):
        mocker.patch.object(config, "RTL_THROTTLE_INTERVAL", 10)
        dp = DataProcessor(mock.MagicMock(), _mk_manager())

        _dispatch(dp, "dev", "temp", 1)
        _dispatch(dp, "dev", "temp", None)
        _dispatch(dp, "dev", "temp", 2)

        vals = dp.buffer["dev"]["temp"]
        assert vals == [1, 2]
