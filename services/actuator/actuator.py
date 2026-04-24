"""AgroSmart actuator service.

Observes every actuator event emitted by field nodes and re-publishes
a normalized stream under `agrosmart/actuator/log` for persistence.
In a real deployment this component would drive relays and flow meters;
here it is an observer that confirms the electrical valve lifecycle.
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


LOG = logging.getLogger("actuator")

SOURCE_TOPIC = "agrosmart/events/actuator/+"
SINK_TOPIC = "agrosmart/actuator/log"


class Actuator:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="actuator-observer",
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_event

    def run(self) -> None:
        self._connect_with_retry()
        self.client.loop_start()
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
            client.subscribe(SOURCE_TOPIC, qos=1)
            LOG.info("subscribed to %s", SOURCE_TOPIC)
        else:
            LOG.error("connection refused: %s", reason_code)

    def _on_event(self, _client, _userdata, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            LOG.error("bad actuator payload on %s: %s", message.topic, exc)
            return

        enriched = {
            **payload,
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_topic": message.topic,
        }
        self.client.publish(SINK_TOPIC, json.dumps(enriched), qos=1)
        LOG.info("valve cycle node=%s volume=%sL reason=%s",
                 payload.get("node_id"), payload.get("volume_delivered_l"),
                 payload.get("reason"))


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def main() -> None:
    _configure_logging()
    actuator = Actuator()

    def _shutdown(signum, _frame):
        LOG.info("received signal %s, stopping", signum)
        actuator.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    LOG.info("actuator observer starting")
    actuator.run()


if __name__ == "__main__":
    main()
