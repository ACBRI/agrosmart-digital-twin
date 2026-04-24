"""AgroSmart central coordinator.

Subscribes to telemetry from all field nodes, queries the weather mock
every few minutes, and publishes irrigation commands on the
`agrosmart/commands/node/{id}/irrigate` topic when the decision engine
says so.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone

import httpx
import paho.mqtt.client as mqtt

from decision import DecisionEngine, WeatherSnapshot


LOG = logging.getLogger("coordinator")

TELEMETRY_PATTERN = "agrosmart/telemetry/node/+"
TOPIC_COMMAND = "agrosmart/commands/node/{node_id}/irrigate"
TOPIC_STATUS = "agrosmart/status/coordinator"
TOPIC_DECISION = "agrosmart/decisions/node/{node_id}"


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


class Coordinator:
    def __init__(self) -> None:
        self.engine = DecisionEngine(
            global_low_pct=_env_float("MOISTURE_LOW", 35.0),
            global_target_pct=_env_float("MOISTURE_TARGET", 70.0),
        )
        self.weather_url = os.environ.get("WEATHER_URL", "http://weather-mock:8000")
        self.weather_cache: WeatherSnapshot = WeatherSnapshot(0.0, 0.0)
        self._stop = threading.Event()

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="coordinator",
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_telemetry

    def run(self) -> None:
        self._connect_with_retry()
        self.client.loop_start()

        weather_thread = threading.Thread(target=self._weather_loop, daemon=True)
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        weather_thread.start()
        heartbeat_thread.start()

        try:
            while not self._stop.wait(1.0):
                pass
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
            client.subscribe(TELEMETRY_PATTERN, qos=1)
            LOG.info("subscribed to %s", TELEMETRY_PATTERN)
        else:
            LOG.error("connection refused: %s", reason_code)

    def _on_telemetry(self, _client, _userdata, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            LOG.error("bad telemetry payload on %s: %s", message.topic, exc)
            return

        node_id = payload.get("node_id")
        if not node_id:
            LOG.warning("telemetry without node_id: %s", payload)
            return

        self.engine.register_zone(
            node_id=node_id,
            crop=payload.get("crop", "unknown"),
            field_capacity_pct=float(payload.get("field_capacity_pct", 72.0)),
            wilting_point_pct=float(payload.get("wilting_point_pct", 20.0)),
        )

        moisture = float(payload["soil_moisture_pct"])
        decision = self.engine.evaluate(node_id, moisture, self.weather_cache)

        self._publish(
            TOPIC_DECISION.format(node_id=node_id),
            {
                "node_id": node_id,
                "timestamp": _now_iso(),
                "moisture_observed_pct": moisture,
                "decision": "irrigate" if decision.should_irrigate else "hold",
                "rationale": decision.rationale,
                "target_pct": decision.target_pct,
                "duration_s": decision.duration_s,
                "weather": decision.weather,
            },
        )

        if decision.should_irrigate:
            command_topic = TOPIC_COMMAND.format(node_id=node_id)
            self._publish(
                command_topic,
                {
                    "node_id": node_id,
                    "action": "irrigate",
                    "target_moisture_pct": decision.target_pct,
                    "duration_s": decision.duration_s,
                    "reason": decision.rationale,
                    "issued_at": _now_iso(),
                },
            )
            LOG.info("IRRIGATE node=%s moisture=%.1f target=%.1f duration=%ss (%s)",
                     node_id, moisture, decision.target_pct, decision.duration_s,
                     decision.rationale)
        else:
            LOG.info("HOLD      node=%s moisture=%.1f (%s)",
                     node_id, moisture, decision.rationale)

    def _weather_loop(self) -> None:
        while not self._stop.is_set():
            try:
                response = httpx.get(f"{self.weather_url}/forecast", timeout=5.0)
                response.raise_for_status()
                data = response.json()
                self.weather_cache = WeatherSnapshot(
                    precipitation_mm_6h=float(data.get("precipitation_mm_6h", 0.0)),
                    rain_probability=float(data.get("rain_probability", 0.0)),
                )
                LOG.debug("weather updated: %s", self.weather_cache)
            except (httpx.HTTPError, ValueError) as exc:
                LOG.warning("weather fetch failed: %s", exc)
            self._stop.wait(30.0)

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            zones = {
                zone_id: {
                    "crop": zone.crop,
                    "low_threshold_pct": round(zone.low_threshold_pct, 2),
                    "target_pct": round(zone.target_pct, 2),
                    "moisture_ewma": round(zone.moisture_ewma, 2) if zone.moisture_ewma else None,
                    "last_action": zone.last_action,
                }
                for zone_id, zone in self.engine.zones.items()
            }
            self._publish(TOPIC_STATUS, {
                "timestamp": _now_iso(),
                "zones": zones,
                "weather": {
                    "precipitation_mm_6h": self.weather_cache.precipitation_mm_6h,
                    "rain_probability": self.weather_cache.rain_probability,
                },
            })
            self._stop.wait(15.0)

    def _publish(self, topic: str, payload: dict) -> None:
        info = self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.warning("publish failed on %s rc=%s", topic, info.rc)


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
    coordinator = Coordinator()

    def _shutdown(signum, _frame):
        LOG.info("received signal %s, stopping", signum)
        coordinator.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    LOG.info("coordinator starting")
    coordinator.run()


if __name__ == "__main__":
    main()
