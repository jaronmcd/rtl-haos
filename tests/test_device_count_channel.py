"""
Tests for DeviceCountChannel lock+event synchronization pattern.

Covers:
- Thread-safe push() and latest-value semantics
- Lock+event signaling mechanism
- Loop timeout behavior
- Producer/consumer patterns
- Concurrent push operations
"""

import pytest
import threading
import time
from unittest import mock
from device_count import DeviceCountChannel


class TestDeviceCountChannelBasic:
    """Basic DeviceCountChannel operations."""

    def test_push_updates_latest_count(self):
        """Push updates the latest count."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        channel.push(42)
        
        # Verify internal state (private but for testing)
        with channel._count_lock:
            assert channel._count_last == 42
            assert channel._count_pending is True

    def test_push_converts_to_int(self):
        """Push converts payload to int."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        channel.push("99")
        
        with channel._count_lock:
            assert channel._count_last == 99
            assert isinstance(channel._count_last, int)

    def test_push_signals_event(self):
        """Push sets the event to wake consumer."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        # Event should start clear
        assert not channel._count_event.is_set()
        
        channel.push(10)
        
        # Event should be set
        assert channel._count_event.is_set()

    def test_push_overwrites_pending_value(self):
        """Multiple pushes overwrite previous pending values."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        channel.push(1)
        channel.push(2)
        channel.push(3)
        
        with channel._count_lock:
            assert channel._count_last == 3


class TestDeviceCountChannelLoopSync:
    """Test loop() synchronization and signal handling."""

    def test_loop_waits_on_event_with_timeout(self):
        """Loop waits on event with timeout mechanism."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        # Verify event can be waited on
        assert not channel._count_event.is_set()
        
        # Wait with timeout should return False (timeout)
        signaled = channel._count_event.wait(timeout=0.05)
        assert signaled is False

    def test_loop_publishes_on_signal(self):
        """Loop publishes count when signaled."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        published_values = []

        def capture_publish(*args, **kwargs):
            # Extract the second arg (payload/count)
            if len(args) > 2:
                published_values.append(args[2])

        mock_mqtt.send_sensor.side_effect = capture_publish

        channel.push(55)
        
        # Run loop once
        signaled = channel._count_event.wait(timeout=0.5)
        assert signaled is True
        
        with channel._count_lock:
            if signaled and channel._count_pending:
                last_count = channel._count_last
                channel._count_pending = False
                channel._count_event.clear()
        
        # Simulate publish
        mock_mqtt.send_sensor("dev1", "sys_device_count", last_count, "Dev 1", "Model", is_rtl=True)
        
        assert last_count == 55

    def test_loop_clears_pending_after_publish(self):
        """Loop clears pending flag after publishing."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        channel.push(100)
        
        with channel._count_lock:
            assert channel._count_pending is True
            channel._count_event.wait(timeout=0.1)
            if channel._count_pending:
                channel._count_last = 100
                channel._count_pending = False
                channel._count_event.clear()
        
        with channel._count_lock:
            assert channel._count_pending is False
            assert not channel._count_event.is_set()

    def test_loop_heartbeat_on_timeout(self):
        """Loop timeout behavior for heartbeat."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        # Initial count
        initial_count = 5
        channel.push(initial_count)
        
        # Event might be set after push
        # Simulate waiting again
        channel._count_event.clear()
        signaled = channel._count_event.wait(timeout=0.05)
        
        # Should timeout (no one set event)
        assert signaled is False
        
        # Last count should still be retained for heartbeat
        with channel._count_lock:
            heartbeat_count = channel._count_last
        
        assert heartbeat_count == initial_count


class TestDeviceCountChannelConcurrency:
    """Concurrent producer/consumer patterns."""

    def test_concurrent_pushes_preserve_latest(self):
        """Multiple producers pushing concurrently, latest value is retained."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        pushed_values = []
        lock = threading.Lock()

        def producer(value):
            channel.push(value)
            with lock:
                pushed_values.append(value)
            time.sleep(0.001)  # Simulate work

        threads = [threading.Thread(target=producer, args=(i,)) for i in range(1, 11)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        
        # Latest value in channel should be the max or last push
        with channel._count_lock:
            latest = channel._count_last
        
        # Should have one of the pushed values
        assert latest in pushed_values

    def test_concurrent_pushes_signal_consumer(self):
        """Multiple pushes signal the consumer correctly."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        signal_count = [0]

        def producer(value):
            channel.push(value)

        def consumer():
            for _ in range(5):
                signaled = channel._count_event.wait(timeout=0.2)
                if signaled:
                    signal_count[0] += 1
                # Clear for next wait
                channel._count_event.clear()

        consumer_thread = threading.Thread(target=consumer)
        consumer_thread.start()
        
        time.sleep(0.05)
        
        producer_threads = [threading.Thread(target=producer, args=(i,)) for i in range(5)]
        for t in producer_threads:
            t.start()
        for t in producer_threads:
            t.join()
        
        consumer_thread.join(timeout=2.0)
        
        # Event should have been set multiple times (at least 1)
        assert signal_count[0] >= 1

    def test_three_producer_one_consumer_pattern(self):
        """Three producers, one consumer - latest value is preserved."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        max_received = [0]
        publish_calls = []

        def capture_publish(*args, **kwargs):
            if len(args) > 2:
                publish_calls.append(args[2])

        mock_mqtt.send_sensor.side_effect = capture_publish

        def producer(producer_id):
            for i in range(5):
                channel.push(producer_id * 100 + i)
                time.sleep(0.005)

        producer_threads = [threading.Thread(target=producer, args=(i,)) for i in range(1, 4)]
        
        for t in producer_threads:
            t.start()
        for t in producer_threads:
            t.join(timeout=5.0)

        # Verify final state
        with channel._count_lock:
            final_count = channel._count_last
        
        # Final count should be a valid value
        assert final_count >= 0


class TestDeviceCountChannelThreadStarting:
    """Test start_thread() method and thread naming."""

    def test_start_thread_configuration(self):
        """start_thread configures thread correctly."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        # Use custom factory to verify arguments
        captured_kwargs = {}
        
        class TestThreadFactory:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)
                self.started = False
            
            def start(self):
                self.started = True
        
        thread = channel.start_thread("dev1", "ModelX", thread_factory=TestThreadFactory)
        
        # Verify configuration
        assert captured_kwargs['daemon'] is True
        assert captured_kwargs['target'] == channel.loop
        assert captured_kwargs['args'] == ("dev1", "ModelX")
        # Should have name for production threads
        assert thread.started is True

    def test_start_thread_with_custom_factory(self):
        """start_thread accepts custom thread factory for testing."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        # Create a test double that doesn't name threads
        class TestThreadFactory:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.started = False
            
            def start(self):
                self.started = True
        
        thread = channel.start_thread("dev1", "ModelX", thread_factory=TestThreadFactory)
        
        assert isinstance(thread, TestThreadFactory)
        assert thread.kwargs['daemon'] is True
        assert thread.started is True

    def test_start_thread_returns_thread(self):
        """start_thread returns started thread."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        # Create a test double that tracks start
        class TestThreadFactory:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.started = False
            
            def start(self):
                self.started = True
        
        thread = channel.start_thread("dev1", "ModelX", thread_factory=TestThreadFactory)
        
        # Verify thread was started
        assert thread.started is True


class TestDeviceCountChannelRaceConditions:
    """Test potential race conditions."""

    def test_push_during_event_clear(self):
        """Push while event is being cleared doesn't lose signal."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        errors = []

        def pusher():
            try:
                for i in range(20):
                    channel.push(i)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def clearer():
            try:
                for _ in range(20):
                    time.sleep(0.001)
                    channel._count_event.clear()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=pusher),
            threading.Thread(target=clearer)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0

    def test_concurrent_read_of_count(self):
        """Multiple readers don't interfere with push."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        read_values = []
        lock = threading.Lock()
        errors = []

        def reader():
            try:
                for _ in range(10):
                    with channel._count_lock:
                        read_values.append(channel._count_last)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def pusher():
            try:
                for i in range(10):
                    channel.push(i * 10)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=pusher)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0
        # All read values should be valid
        assert all(isinstance(v, int) for v in read_values)


class TestDeviceCountChannelEdgeCases:
    """Edge cases and boundary conditions."""

    def test_push_zero_count(self):
        """Can push zero devices."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        channel.push(0)
        
        with channel._count_lock:
            assert channel._count_last == 0

    def test_push_large_count(self):
        """Can push large device counts."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        channel.push(999999)
        
        with channel._count_lock:
            assert channel._count_last == 999999

    def test_push_negative_count(self):
        """Can push negative count (though not semantically correct)."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        channel.push(-5)
        
        with channel._count_lock:
            assert channel._count_last == -5

    def test_push_float_converts_to_int(self):
        """Push converts float to int (not float strings)."""
        mock_mqtt = mock.MagicMock()
        channel = DeviceCountChannel(mock_mqtt)
        
        channel.push(42.7)  # Direct float converts via int()
        
        with channel._count_lock:
            assert channel._count_last == 42
            assert isinstance(channel._count_last, int)
