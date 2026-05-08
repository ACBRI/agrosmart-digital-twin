"""MQTT to TimescaleDB ingestor for AgroSmart.

Subscribes to the three persistent streams of the digital twin
(telemetry, actuator log, coordinator decisions) and writes each
message into its corresponding hypertable. Connection failures on
either side trigger bounded exponential backoff.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import psycopg


LOG = logging.getLogger("ingestor")

TOPIC_TELEMETRY = "agrosmart/telemetry/node/+"
TOPIC_ACTUATOR = "agrosmart/actuator/log"
TOPIC_DECISION = "agrosmart/decisions/node/+"


class Ingestor:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self.conn: psycopg.Connection | None = None
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="ingestor",
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def run(self) -> None:
        self._open_db()
        self._connect_mqtt()
        self.client.loop_start()
        try:
            while not self._stop.wait(1.0):
                pass
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            if self.conn:
                self.conn.close()

    def stop(self) -> None:
        self._stop.set()

    def _open_db(self) -> None:
        dsn = (
            f"host={os.environ['DB_HOST']} "
            f"port={os.environ.get('DB_PORT', '5432')} "
            f"dbname={os.environ['DB_NAME']} "
            f"user={os.environ['DB_USER']} "
            f"password={os.environ['DB_PASSWORD']}"
        )
        attempt = 0
        while not self._stop.is_set():
            try:
                self.conn = psycopg.connect(dsn, autocommit=True)
                LOG.info("connected to TimescaleDB")
                return
            except psycopg.OperationalError as exc:
                attempt += 1
                delay = min(30, 2 ** min(attempt, 5))
                LOG.warning("DB connect failed (%s); retry in %ss", exc, delay)
                time.sleep(delay)

    def _connect_mqtt(self) -> None:
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
        if reason_code != 0:
            LOG.error("connection refused: %s", reason_code)
            return
        for topic in (TOPIC_TELEMETRY, TOPIC_ACTUATOR, TOPIC_DECISION):
            client.subscribe(topic, qos=1)
            LOG.info("subscribed to %s", topic)

    def _on_message(self, _client, _userdata, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            LOG.error("bad payload on %s: %s", message.topic, exc)
            return

        try:
            if message.topic.startswith("agrosmart/telemetry/"):
                self._insert_telemetry(payload)
            elif message.topic == TOPIC_ACTUATOR:
                self._insert_actuator(payload)
            elif message.topic.startswith("agrosmart/decisions/"):
                self._insert_decision(payload)
        except psycopg.Error as exc:
            LOG.error("DB insert failed: %s", exc)
            self._reopen_db()

    def _insert_telemetry(self, payload: dict) -> None:
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry
                    (time, node_id, crop, soil_moisture_pct, soil_temp_c,
                     ambient_temp_c, ambient_humidity_pct, battery_v)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _parse_ts(payload.get("timestamp")),
                    payload["node_id"],
                    payload.get("crop", "unknown"),
                    payload["soil_moisture_pct"],
                    payload["soil_temp_c"],
                    payload["ambient_temp_c"],
                    payload["ambient_humidity_pct"],
                    payload["battery_v"],
                ),
            )

    def _insert_actuator(self, payload: dict) -> None:
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO irrigation_events
                    (time, node_id, action, duration_s, volume_l, reason,
                     moisture_before, moisture_target)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _parse_ts(payload.get("observed_at") or payload.get("timestamp")),
                    payload["node_id"],
                    "irrigate",
                    payload.get("duration_s"),
                    payload.get("volume_delivered_l"),
                    payload.get("reason"),
                    payload.get("moisture_before"),
                    payload.get("moisture_after"),
                ),
            )

    def _insert_decision(self, payload: dict) -> None:
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO coordinator_decisions
                    (time, node_id, decision, rationale, weather_forecast)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (
                    _parse_ts(payload.get("timestamp")),
                    payload["node_id"],
                    payload["decision"],
                    payload.get("rationale"),
                    json.dumps(payload.get("weather", {})),
                ),
            )

            prediction = payload.get("prediction") or {}
            recommendation = prediction.get("recommendation")
            if recommendation and recommendation != "n/a":
                cur.execute(
                    """
                    INSERT INTO predictor_decisions
                        (time, node_id, recommendation,
                         projected_moisture_in_24h_pct, estimated_saving_pct, rationale)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        _parse_ts(payload.get("timestamp")),
                        payload["node_id"],
                        recommendation,
                        prediction.get("projected_moisture_in_24h_pct"),
                        prediction.get("estimated_saving_pct"),
                        prediction.get("rationale"),
                    ),
                )

    def _reopen_db(self) -> None:
        try:
            if self.conn:
                self.conn.close()
        finally:
            self.conn = None
        self._open_db()


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def main() -> None:
    _configure_logging()
    ingestor = Ingestor()

    def _shutdown(signum, _frame):
        LOG.info("received signal %s, stopping", signum)
        ingestor.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    LOG.info("telemetry ingestor starting")
    ingestor.run()


if __name__ == "__main__":
    main()
