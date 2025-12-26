#!/usr/bin/env python3
"""
battery_ok_mqtt_sim.py

Simulate rtl-haos 'battery_ok' published as a Home Assistant binary_sensor battery entity.

- battery_ok semantics:
    battery_ok=1/True  -> battery is OK
    battery_ok=0/False -> battery is LOW

- Home Assistant battery binary_sensor semantics:
    state ON  -> battery LOW
    state OFF -> battery OK

This script publishes HA MQTT Discovery config (retained) and then simulates
a throttle interval where battery_ok is sampled repeatedly but only the LAST
sample is published at the end of the interval.

Requires: pip install paho-mqtt
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass
from typing import Optional

import paho.mqtt.client as mqtt


@dataclass
class MqttCfg:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    client_id: str
    keepalive: int = 30
    tls: bool = False


def build_discovery_payload(
    name: str,
    unique_id: str,
    state_topic: str,
    availability_topic: Optional[str],
    device_id: str,
) -> dict:
    payload = {
        "name": name,
        "unique_id": unique_id,
        "device_class": "battery",
        "state_topic": state_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        # optional but nice:
        "expire_after": 0,  # keep last known
    }

    if availability_topic:
        payload["availability_topic"] = availability_topic
        payload["payload_available"] = "online"
        payload["payload_not_available"] = "offline"

    payload["device"] = {
        "identifiers": [device_id],
        "name": f"Battery_OK Simulator ({device_id})",
        "manufacturer": "Test",
        "model": "MQTT Simulator",
    }

    return payload


def battery_ok_to_ha_state(battery_ok: bool) -> str:
    # invert: True(ok) -> OFF, False(low) -> ON
    return "OFF" if battery_ok else "ON"


def connect(cfg: MqttCfg) -> mqtt.Client:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.client_id)

    if cfg.username:
        c.username_pw_set(cfg.username, cfg.password or "")

    if cfg.tls:
        c.tls_set()  # uses system CAs

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            raise RuntimeError(f"MQTT connect failed: {reason_code}")

    c.on_connect = on_connect
    c.connect(cfg.host, cfg.port, cfg.keepalive)
    c.loop_start()
    return c


def publish_retained(client: mqtt.Client, topic: str, payload: str) -> None:
    info = client.publish(topic, payload=payload, qos=0, retain=True)
    info.wait_for_publish()


def publish_non_retained(client: mqtt.Client, topic: str, payload: str) -> None:
    info = client.publish(topic, payload=payload, qos=0, retain=False)
    info.wait_for_publish()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--username", default="rtl")
    ap.add_argument("--password", default="rtl123")
    ap.add_argument("--tls", action="store_true")

    ap.add_argument("--discovery-prefix", default="homeassistant")
    ap.add_argument("--entity-id", default="test_battery_ok")
    ap.add_argument("--device-id", default="battery_ok_sim")
    ap.add_argument("--name", default="Test Battery Low")

    ap.add_argument("--state-topic", default=None, help="Override state topic")
    ap.add_argument("--availability-topic", default=None, help="Optional availability topic")

    ap.add_argument("--throttle-seconds", type=int, default=30)
    ap.add_argument("--sample-every-ms", type=int, default=1000)

    ap.add_argument("--pattern", choices=["random", "flip", "all_ok", "all_low"], default="flip")
    ap.add_argument("--seed", type=int, default=1)

    ap.add_argument("--retain-state", action="store_true", help="Publish final state as retained")
    ap.add_argument("--cleanup", action="store_true", help="Clear retained discovery/state topics and exit")

    args = ap.parse_args()

    unique_id = f"{args.entity_id}_battery_low"
    config_topic = f"{args.discovery_prefix}/binary_sensor/{unique_id}/config"
    state_topic = args.state_topic or f"test/{args.entity_id}/state"

    cfg = MqttCfg(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        client_id=f"{args.device_id}_{int(time.time())}",
        tls=args.tls,
    )

    client = connect(cfg)

    try:
        if args.cleanup:
            # Clear retained discovery + (optional) retained state
            publish_retained(client, config_topic, "")
            publish_retained(client, state_topic, "")
            if args.availability_topic:
                publish_retained(client, args.availability_topic, "")
            print(f"Cleared retained config: {config_topic}")
            print(f"Cleared retained state:  {state_topic}")
            return 0

        # Publish discovery (retained)
        discovery = build_discovery_payload(
            name=args.name,
            unique_id=unique_id,
            state_topic=state_topic,
            availability_topic=args.availability_topic,
            device_id=args.device_id,
        )
        publish_retained(client, config_topic, json.dumps(discovery))
        print(f"Published discovery config (retained): {config_topic}")
        print(f"State topic: {state_topic}")

        # Optional availability
        if args.availability_topic:
            publish_retained(client, args.availability_topic, "online")
            print(f"Availability online (retained): {args.availability_topic}")

        # Simulate throttle interval: sample repeatedly, publish only LAST at end
        random.seed(args.seed)
        samples = max(1, int((args.throttle_seconds * 1000) / max(1, args.sample_every_ms)))

        last_valid: Optional[bool] = None
        for i in range(samples):
            if args.pattern == "random":
                battery_ok = bool(random.getrandbits(1))
            elif args.pattern == "flip":
                battery_ok = (i % 2 == 0)  # ok, low, ok, low...
            elif args.pattern == "all_ok":
                battery_ok = True
            else:  # all_low
                battery_ok = False

            last_valid = battery_ok
            print(f"sample[{i+1}/{samples}] battery_ok={int(battery_ok)} (buffered; not published)")
            time.sleep(args.sample_every_ms / 1000.0)

        assert last_valid is not None
        ha_state = battery_ok_to_ha_state(last_valid)

        if args.retain_state:
            publish_retained(client, state_topic, ha_state)
            print(f"FLUSH publish (retained): battery_ok={int(last_valid)} -> HA state={ha_state}")
        else:
            publish_non_retained(client, state_topic, ha_state)
            print(f"FLUSH publish: battery_ok={int(last_valid)} -> HA state={ha_state}")

        print("\nIn Home Assistant:")
        print("- Entity should appear as a Binary Sensor with device_class 'battery'")
        print("- ON means LOW, OFF means OK\n")

        return 0

    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
