"""AgroSmart field node simulator.

Emulates an ESP32 low-power node that wakes every `TELEMETRY_INTERVAL_S`
simulated seconds, samples soil and ambient sensors, publishes telemetry
over MQTT, and reacts to irrigation commands. Simulation time advances
at `TIME_SCALE` simulated seconds per real second.
"""

from __future__ import annotations

import json
import logging
import os
import random
import signal
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from physics import AmbientState, SoilProfile, SoilState, diurnal_ambient


LOG = logging.getLogger("node")


TOPIC_TELEMETRY = "agrosmart/telemetry/node/{node_id}"
TOPIC_COMMAND = "agrosmart/commands/node/{node_id}/irrigate"
TOPIC_ACTUATOR_EVENT = "agrosmart/events/actuator/{node_id}"


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class Node:
    def __init__(self) -> None:
        self.node_id = os.environ.get("NODE_ID", "zone-x")
        self.profile = SoilProfile(
            crop=os.environ.get("NODE_CROP", "generic"),
            field_capacity_pct=_env_float("NODE_FIELD_CAPACITY", 72.0),
            wilting_point_pct=_env_float("NODE_WILTING_POINT", 20.0),
        )
        self.soil = SoilState(self.profile, _env_float("NODE_INITIAL_MOISTURE", 50.0))
        self.time_scale = max(1.0, _env_float("TIME_SCALE", 60.0))
        self.telemetry_interval_s = _env_int("TELEMETRY_INTERVAL_S", 900)
        self.physics_step_s = 30

        self.sim_epoch = time.time()
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"node-{self.node_id}",
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.battery_v = 12.6

    def run(self) -> None:
        self._connect_with_retry()
        self.client.loop_start()

        physics_thread = threading.Thread(target=self._physics_loop, daemon=True)
        physics_thread.start()

        try:
            self._telemetry_loop()
        finally:
            self.client.loop_stop()
            self.client.disconnect()

    def stop(self) -> None:
        self._stop.set()

    def _connect_with_retry(self) -> None:
        host = os.environ["MQTT_HOST"]
        port = int(os.environ.get("MQTT_PORT", "1883"))
        attempt = 0
        while not self._stop.is_set():
            try:
                self.client.connect(host, port, keepalive=60)
                LOG.info("connected to MQTT broker %s:%s", host, port)
                return
            except OSError as exc:
                attempt += 1
                delay = min(30, 2 ** min(attempt, 5))
                LOG.warning("MQTT connect failed (%s); retry in %ss", exc, delay)
                time.sleep(delay)

    def _on_connect(self, client: mqtt.Client, _userdata, _flags, reason_code, _props=None) -> None:
        if reason_code == 0:
            topic = TOPIC_COMMAND.format(node_id=self.node_id)
            client.subscribe(topic, qos=1)
            LOG.info("subscribed to %s", topic)
        else:
            LOG.error("connection refused: %s", reason_code)

    def _on_message(self, _client, _userdata, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            LOG.error("bad command payload on %s: %s", message.topic, exc)
            return

        if payload.get("action") != "irrigate":
            return

        target_pct = float(payload.get("target_moisture_pct", self.profile.field_capacity_pct * 0.9))
        duration_s = int(payload.get("duration_s", 600))
        reason = payload.get("reason", "unspecified")

        with self._lock:
            before = self.soil.moisture_pct
            delta = max(0.0, target_pct - before)
            applied = self.soil.irrigate(delta)

        LOG.info(
            "irrigation applied node=%s before=%.1f after=%.1f duration=%ss reason=%s",
            self.node_id, before, self.soil.moisture_pct, duration_s, reason,
        )
        self._publish(
            TOPIC_ACTUATOR_EVENT.format(node_id=self.node_id),
            {
                "node_id": self.node_id,
                "timestamp": _now_iso(),
                "valve_state": "open_to_closed",
                "duration_s": duration_s,
                "volume_delivered_l": round(applied * 2.0, 2),
                "moisture_before": round(before, 2),
                "moisture_after": round(self.soil.moisture_pct, 2),
                "reason": reason,
            },
        )

    def _physics_loop(self) -> None:
        last_real = time.time()
        while not self._stop.is_set():
            now_real = time.time()
            real_dt = now_real - last_real
            last_real = now_real

            sim_dt = real_dt * self.time_scale
            self.sim_epoch += sim_dt

            ambient = diurnal_ambient(self.sim_epoch)
            with self._lock:
                self.soil.step(ambient, sim_dt)
                self._last_ambient = ambient

            self._drain_battery(sim_dt)
            time.sleep(self.physics_step_s / self.time_scale)

    def _telemetry_loop(self) -> None:
        interval_real = self.telemetry_interval_s / self.time_scale
        jitter = interval_real * 0.05
        while not self._stop.is_set():
            with self._lock:
                ambient = getattr(self, "_last_ambient", diurnal_ambient(self.sim_epoch))
                moisture = self.soil.moisture_pct
                soil_temp = self.soil.soil_temp_c

            reading = {
                "node_id": self.node_id,
                "crop": self.profile.crop,
                "timestamp": _now_iso(),
                "soil_moisture_pct": round(moisture + random.gauss(0, 0.4), 2),
                "soil_temp_c": round(soil_temp, 2),
                "ambient_temp_c": round(ambient.temp_c, 2),
                "ambient_humidity_pct": round(ambient.humidity_pct, 2),
                "battery_v": round(self.battery_v, 2),
                "field_capacity_pct": self.profile.field_capacity_pct,
                "wilting_point_pct": self.profile.wilting_point_pct,
            }
            self._publish(TOPIC_TELEMETRY.format(node_id=self.node_id), reading)

            sleep_for = max(0.5, interval_real + random.uniform(-jitter, jitter))
            self._stop.wait(sleep_for)

    def _publish(self, topic: str, payload: dict) -> None:
        info = self.client.publish(topic, json.dumps(payload), qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.warning("publish failed on %s rc=%s", topic, info.rc)

    def _drain_battery(self, sim_dt_seconds: float) -> None:
        hours = sim_dt_seconds / 3600.0
        self.battery_v = max(11.4, self.battery_v - 0.0004 * hours + random.gauss(0, 0.001))
        if random.random() < 0.0005:
            self.battery_v = min(12.8, self.battery_v + 0.2)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def main() -> None:
    _configure_logging()
    node = Node()

    def _shutdown(signum, _frame):
        LOG.info("received signal %s, stopping", signum)
        node.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    LOG.info(
        "node %s (crop=%s, FC=%.1f, WP=%.1f) starting at moisture=%.1f",
        node.node_id, node.profile.crop,
        node.profile.field_capacity_pct, node.profile.wilting_point_pct,
        node.soil.moisture_pct,
    )
    node.run()


if __name__ == "__main__":
    main()
