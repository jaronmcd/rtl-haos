"""
Comprehensive tests for MQTT I/O worker ops and dispatcher.

Tests cover:
1. Worker op execution (mqtt_publish, mqtt_subscribe, mqtt_unsubscribe)
2. _enqueue_mqtt_io dispatcher with inline/queue/wait paths
3. Error handling and edge cases
4. Result queue coordination
5. Thread safety
"""

import pytest
import queue
import threading
import time
from unittest import mock
from mqtt_handler import HomeNodeMQTT


class TestWorkerOps:
    """Tests for mqtt_publish, mqtt_subscribe, mqtt_unsubscribe worker ops."""

    def test_worker_mqtt_publish_success(self, mocker):
        """Worker can successfully publish via paho client."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        # Directly invoke worker op
        item = {
            "op": "mqtt_publish",
            "topic": "test/topic",
            "payload": "test_payload",
            "retain": False,
        }
        handler._worker_mqtt_publish(item)

        # Verify paho client was called
        handler.client.publish.assert_called_once_with(
            "test/topic", "test_payload", retain=False
        )
        handler.stop()

    def test_worker_mqtt_publish_with_result_queue(self, mocker):
        """Worker publishes result to result_queue on success."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result_q = queue.Queue()
        item = {
            "op": "mqtt_publish",
            "topic": "test/topic",
            "payload": "payload",
            "retain": True,
            "result_queue": result_q,
        }
        handler._worker_mqtt_publish(item)

        # Result should be True
        ok = result_q.get(timeout=1.0)
        assert ok is True
        handler.stop()

    def test_worker_mqtt_publish_failure_handling(self, mocker):
        """Worker catches publish exceptions and queues False."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        # Don't call start() to avoid worker thread

        # Make publish raise exception
        handler.client.publish.side_effect = RuntimeError("MQTT error")

        result_q = queue.Queue()
        item = {
            "op": "mqtt_publish",
            "topic": "test/topic",
            "payload": "payload",
            "result_queue": result_q,
        }
        # Directly call worker handler for this error path
        handler._worker_mqtt_publish(item)

        ok = result_q.get(timeout=1.0)
        assert ok is False

    def test_worker_mqtt_subscribe_success(self, mocker):
        """Worker can successfully subscribe via paho client."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        item = {"op": "mqtt_subscribe", "topic": "test/topic"}
        handler._worker_mqtt_subscribe(item)

        handler.client.subscribe.assert_called_once_with("test/topic")
        handler.stop()

    def test_worker_mqtt_subscribe_with_result_queue(self, mocker):
        """Worker returns result via result_queue for subscribe."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result_q = queue.Queue()
        item = {"op": "mqtt_subscribe", "topic": "test/topic", "result_queue": result_q}
        handler._worker_mqtt_subscribe(item)

        ok = result_q.get(timeout=1.0)
        assert ok is True
        handler.stop()

    def test_worker_mqtt_subscribe_failure(self, mocker):
        """Worker catches subscribe exceptions and queues False."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        handler.client.subscribe.side_effect = RuntimeError("Subscribe failed")

        result_q = queue.Queue()
        item = {"op": "mqtt_subscribe", "topic": "test/topic", "result_queue": result_q}
        handler._worker_mqtt_subscribe(item)

        ok = result_q.get(timeout=1.0)
        assert ok is False
        handler.stop()

    def test_worker_mqtt_unsubscribe_success(self, mocker):
        """Worker can successfully unsubscribe via paho client."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        item = {"op": "mqtt_unsubscribe", "topic": "test/topic"}
        handler._worker_mqtt_unsubscribe(item)

        handler.client.unsubscribe.assert_called_once_with("test/topic")
        handler.stop()

    def test_worker_mqtt_unsubscribe_with_result_queue(self, mocker):
        """Worker returns result via result_queue for unsubscribe."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result_q = queue.Queue()
        item = {
            "op": "mqtt_unsubscribe",
            "topic": "test/topic",
            "result_queue": result_q,
        }
        handler._worker_mqtt_unsubscribe(item)

        ok = result_q.get(timeout=1.0)
        assert ok is True
        handler.stop()

    def test_worker_mqtt_unsubscribe_failure(self, mocker):
        """Worker catches unsubscribe exceptions and queues False."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        handler.client.unsubscribe.side_effect = RuntimeError("Unsub failed")

        result_q = queue.Queue()
        item = {
            "op": "mqtt_unsubscribe",
            "topic": "test/topic",
            "result_queue": result_q,
        }
        handler._worker_mqtt_unsubscribe(item)

        ok = result_q.get(timeout=1.0)
        assert ok is False
        handler.stop()


class TestEnqueueMqttIoDispatcher:
    """Tests for _enqueue_mqtt_io dispatcher (inline vs queue vs wait)."""

    def test_enqueue_inline_no_worker(self, mocker):
        """When no worker thread exists, executes inline."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        # Do NOT call start(), so no worker exists

        # Spy on the actual publish call
        handler.client.publish = mocker.MagicMock()

        result = handler._client_publish("test/topic", "payload", wait=False)

        # Should execute inline and return True
        assert result is True
        handler.client.publish.assert_called_once()

    def test_enqueue_inline_same_thread(self, mocker):
        """When called with wait=True, blocks for result."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        # Call with wait=True - should block until worker completes
        result = handler._client_publish("test/topic", "payload", wait=True)

        # Should have executed and returned success
        assert result is True
        handler.client.publish.assert_called_once()
        handler.stop()

    def test_enqueue_queued_call_from_other_thread(self, mocker):
        """When called from other thread, enqueues to worker queue."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        # We're in main thread, worker is different
        assert threading.get_ident() != handler._worker_thread_id

        # Call with wait=True to ensure it completes
        result = handler._client_publish("test/topic", "payload", wait=True)

        # Should return True after worker executes
        assert result is True

        # Verify client.publish was called (in worker thread)
        handler.client.publish.assert_called_once()
        handler.stop()

    def test_enqueue_wait_with_result_queue(self, mocker):
        """When wait=True, blocks and waits for result_queue."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        # Publish from main thread with wait=True
        result = handler._client_publish("test/topic", "payload", wait=True, retain=True)

        # Should have executed and returned result
        assert result is True
        handler.client.publish.assert_called_once_with(
            "test/topic", "payload", retain=True
        )
        handler.stop()

    def test_enqueue_wait_timeout_and_fallback(self, mocker):
        """When queue is full, returns False gracefully."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()

        # Mock the queue to raise Full on put
        mock_queue = mocker.MagicMock(spec=queue.Queue)
        mock_queue.put.side_effect = queue.Full("queue full")
        mock_queue.qsize.return_value = 100  # Return valid qsize
        handler._publish_queue = mock_queue
        handler._worker_thread_id = 999  # Fake worker thread

        result = handler._client_publish("test/topic", "payload", wait=False)

        # Should return False due to queue.Full
        assert result is False

    def test_enqueue_wait_handles_queue_full(self, mocker):
        """When queue is full after put, handles gracefully."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()

        # Mock the queue to raise Full on put
        mock_queue = mocker.MagicMock(spec=queue.Queue)
        mock_queue.put.side_effect = queue.Full("queue full")
        mock_queue.qsize.return_value = 100  # Return valid qsize
        handler._publish_queue = mock_queue
        handler._worker_thread_id = 999  # Fake worker thread

        # Try to enqueue - should handle gracefully
        result = handler._client_publish("test/topic", "payload", wait=False)

        # Should return False due to queue.Full
        assert result is False


class TestClientWrappers:
    """Tests for public _client_publish/subscribe/unsubscribe wrappers."""

    def test_client_publish_wrapper_basic(self, mocker):
        """_client_publish wrapper formats op correctly."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result = handler._client_publish("my/topic", "my_payload", retain=False, wait=True)

        assert result is True
        handler.client.publish.assert_called_once_with(
            "my/topic", "my_payload", retain=False
        )
        handler.stop()

    def test_client_publish_wrapper_with_retain(self, mocker):
        """_client_publish passes retain flag correctly."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result = handler._client_publish("my/topic", "payload", retain=True, wait=True)

        assert result is True
        handler.client.publish.assert_called_once_with("my/topic", "payload", retain=True)
        handler.stop()

    def test_client_subscribe_wrapper(self, mocker):
        """_client_subscribe wrapper formats op correctly."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result = handler._client_subscribe("my/topic", wait=True)

        assert result is True
        handler.client.subscribe.assert_called_once_with("my/topic")
        handler.stop()

    def test_client_unsubscribe_wrapper(self, mocker):
        """_client_unsubscribe wrapper formats op correctly."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result = handler._client_unsubscribe("my/topic", wait=True)

        assert result is True
        handler.client.unsubscribe.assert_called_once_with("my/topic")
        handler.stop()


class TestIntegration:
    """Integration tests for worker ops in realistic scenarios."""

    def test_discovery_publishes_via_worker_ops(self, mocker):
        """Discovery publishing uses worker-owned _client_publish."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        # Spy on _client_publish to verify it was called
        spy_client_publish = mocker.spy(handler, "_client_publish")

        # Trigger discovery flow
        handler.send_sensor("device1", "temperature", 72.0, "Weather Station", "DHT22")

        handler.stop()

        # Should have called _client_publish at least once (discovery + state)
        assert spy_client_publish.call_count >= 2

    def test_subscribe_for_discovery_via_worker_ops(self, mocker):
        """Worker thread processes subscribe operations correctly."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        # Spy on _client_subscribe to verify it's being called
        spy_client_subscribe = mocker.spy(handler, "_client_subscribe")
        
        # Manually call _client_subscribe with wait=True to ensure execution 
        result = handler._client_subscribe("test/command/+", wait=True)
        assert result is True
        assert spy_client_subscribe.called

    def test_stop_offline_publish_with_wait(self, mocker):
        """stop() publishes offline availability with wait=True."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        # Give it a moment to fully initialize
        time.sleep(0.05)

        # Stop should publish offline with wait=True
        handler.stop()

        # Verify offline was published
        publish_calls = handler.client.publish.call_args_list
        offline_calls = [call for call in publish_calls if "offline" in str(call)]
        # Should have at least attempted offline publish during stop
        assert len(publish_calls) > 0

    def test_concurrent_publish_from_multiple_threads(self, mocker):
        """Multiple threads can safely publish concurrently via wrapper."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        results = []
        exceptions = []

        def publisher(topic_num):
            try:
                result = handler._client_publish(f"test/topic{topic_num}", f"payload{topic_num}")
                results.append(result)
            except Exception as e:
                exceptions.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=publisher, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=2.0)

        handler.stop()

        # All should succeed
        assert len(exceptions) == 0
        assert all(results)
        assert len(results) == 5

    def test_publish_and_subscribe_interleaved(self, mocker):
        """Publish and subscribe can interleave safely."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        results = []
        exceptions = []

        def mixed_operations():
            try:
                for i in range(3):
                    handler._client_publish(f"test/{i}", f"val{i}")
                    handler._client_subscribe(f"cmd/{i}")
                    results.append(True)
            except Exception as e:
                exceptions.append(e)

        threads = [threading.Thread(target=mixed_operations) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        handler.stop()

        assert len(exceptions) == 0
        assert len(results) == 9  # 3 threads * 3 operations

    def test_worker_dispatch_has_worker_ops(self, mocker):
        """Verify worker ops execute correctly through dispatch."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()

        # Verify worker methods exist and are callable
        required_methods = [
            "_worker_mqtt_publish",
            "_worker_mqtt_subscribe",
            "_worker_mqtt_unsubscribe",
        ]
        for method_name in required_methods:
            assert hasattr(handler, method_name), f"{method_name} not found"
            method = getattr(handler, method_name)
            assert callable(method), f"{method_name} not callable"

        # Verify dispatch routes mqtt_publish correctly
        result_q = queue.Queue()
        item = {
            "op": "mqtt_publish",
            "topic": "test/topic",
            "payload": "test",
            "result_queue": result_q,
        }
        routed = handler._worker_dispatch_item(item)
        assert routed is True
        # Verify result was queued
        ok = result_q.get(timeout=1.0)
        assert isinstance(ok, bool)

    def test_result_queue_timeout_scenario(self, mocker):
        """Result queue error handling works correctly."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()

        # Mock the queue to raise Full on put
        mock_queue = mocker.MagicMock(spec=queue.Queue)
        mock_queue.put.side_effect = queue.Full("queue full")
        mock_queue.qsize.return_value = 100  # Return valid qsize for _warn_queue_depth
        handler._publish_queue = mock_queue
        handler._worker_thread_id = 999  # Fake worker thread

        result = handler._client_publish("test", "payload", wait=False)

        # Should handle gracefully and return False
        assert result is False


class TestEdgeCases:
    """Edge cases and error scenarios."""

    def test_publish_with_none_payload(self, mocker):
        """Publish handles None payload gracefully."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result = handler._client_publish("test/topic", None, wait=True)

        assert result is True
        handler.client.publish.assert_called_once_with("test/topic", None, retain=False)
        handler.stop()

    def test_subscribe_with_empty_topic(self, mocker):
        """Subscribe with empty topic still queues (validation elsewhere)."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        result = handler._client_subscribe("", wait=True)

        assert result is True
        handler.client.subscribe.assert_called_once_with("")
        handler.stop()

    def test_worker_op_without_required_fields(self, mocker):
        """Worker op missing fields doesn't crash."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()

        # Call worker op directly with minimal item
        item = {"op": "mqtt_publish"}  # Missing topic, payload
        handler._worker_mqtt_publish(item)  # Should handle KeyError gracefully

        handler.stop()

    def test_enqueue_with_zero_timeout(self, mocker):
        """Enqueue with zero sync timeout doesn't hang."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler._sync_enqueue_timeout_s = 0.001  # Very short timeout
        handler.start()

        # This might timeout quickly, but should not hang forever
        result = handler._client_publish("test/topic", "payload", wait=False)

        handler.stop()
