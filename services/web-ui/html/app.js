/**
 * AgroSmart operator panel.
 *
 * Subscribes to the MQTT broker over WebSockets, renders a card per field
 * zone with live soil-moisture visualisation, and keeps running logs for
 * coordinator decisions and irrigation events.
 */

(function () {
    "use strict";

    const MQTT_HOST = window.location.hostname || "localhost";
    const MQTT_WS_PORT = 18831;
    const WEATHER_URL = `http://${MQTT_HOST}:8096`;

    const TOPIC_TELEMETRY = "agrosmart/telemetry/node/+";
    const TOPIC_DECISION = "agrosmart/decisions/node/+";
    const TOPIC_ACTUATOR = "agrosmart/actuator/log";
    const TOPIC_STATUS = "agrosmart/status/coordinator";

    const LOG_LIMIT = 40;

    const state = {
        zones: new Map(),
        decisions: [],
        events: [],
        weather: null,
    };

    const el = {
        zonesRoot: document.getElementById("zones"),
        decisionLog: document.getElementById("decision-log"),
        irrigationLog: document.getElementById("irrigation-log"),
        connectionDot: document.getElementById("connection-dot"),
        connectionLabel: document.getElementById("connection-label"),
        weatherBadge: document.getElementById("weather-badge"),
        injectRainBtn: document.getElementById("inject-rain"),
    };

    el.injectRainBtn.addEventListener("click", () => injectRain());

    const url = `ws://${MQTT_HOST}:${MQTT_WS_PORT}/mqtt`;
    const client = mqtt.connect(url, {
        clientId: `web-ui-${Math.random().toString(36).slice(2, 10)}`,
        reconnectPeriod: 2000,
        clean: true,
    });

    client.on("connect", () => {
        setConnection(true);
        client.subscribe([TOPIC_TELEMETRY, TOPIC_DECISION, TOPIC_ACTUATOR, TOPIC_STATUS], { qos: 1 });
    });

    client.on("reconnect", () => setConnection(false, "Reintentando conexión…"));
    client.on("offline", () => setConnection(false, "Broker no disponible"));
    client.on("error", (err) => setConnection(false, `Error MQTT: ${err.message}`));

    client.on("message", (topic, payload) => {
        let data;
        try {
            data = JSON.parse(payload.toString());
        } catch (_) {
            return;
        }

        if (topic.startsWith("agrosmart/telemetry/node/")) {
            handleTelemetry(data);
        } else if (topic.startsWith("agrosmart/decisions/node/")) {
            handleDecision(data);
        } else if (topic === TOPIC_ACTUATOR) {
            handleActuator(data);
        } else if (topic === TOPIC_STATUS) {
            handleStatus(data);
        }
    });

    function setConnection(isOn, label) {
        el.connectionDot.classList.toggle("dot-on", isOn);
        el.connectionDot.classList.toggle("dot-off", !isOn);
        el.connectionLabel.textContent = label || (isOn ? "Conectado al broker MQTT" : "Desconectado");
    }

    function handleTelemetry(reading) {
        const { node_id, crop, soil_moisture_pct, soil_temp_c, ambient_temp_c,
            ambient_humidity_pct, battery_v, field_capacity_pct, wilting_point_pct, timestamp } = reading;

        const zone = state.zones.get(node_id) ?? {
            node_id,
            crop,
            field_capacity_pct,
            wilting_point_pct,
            low_threshold_pct: 35,
            target_pct: 70,
            status: "normal",
            last_moisture: null,
            last_update: null,
        };

        zone.crop = crop;
        zone.last_moisture = soil_moisture_pct;
        zone.last_soil_temp = soil_temp_c;
        zone.last_ambient_temp = ambient_temp_c;
        zone.last_ambient_humidity = ambient_humidity_pct;
        zone.battery_v = battery_v;
        zone.last_update = timestamp;
        zone.field_capacity_pct = field_capacity_pct;
        zone.wilting_point_pct = wilting_point_pct;

        state.zones.set(node_id, zone);
        renderZones();
    }

    function handleDecision(decision) {
        state.decisions.unshift(decision);
        state.decisions = state.decisions.slice(0, LOG_LIMIT);

        const zone = state.zones.get(decision.node_id);
        if (zone) {
            if (decision.decision === "irrigate") {
                zone.status = "irrigating";
            } else if (decision.rationale && decision.rationale.toLowerCase().includes("rain")) {
                zone.status = "low";
            } else {
                zone.status = "normal";
            }
            zone.low_threshold_pct = decision.target_pct ?? zone.low_threshold_pct;
            renderZones();
        }

        renderDecisions();
    }

    function handleActuator(event) {
        state.events.unshift(event);
        state.events = state.events.slice(0, LOG_LIMIT);
        renderEvents();
    }

    function handleStatus(status) {
        state.weather = status.weather || null;
        renderWeather();
    }

    function renderZones() {
        const zones = Array.from(state.zones.values()).sort((a, b) => a.node_id.localeCompare(b.node_id));
        el.zonesRoot.innerHTML = zones.map(renderZoneCard).join("");
    }

    function renderZoneCard(z) {
        const fc = z.field_capacity_pct ?? 72;
        const wp = z.wilting_point_pct ?? 20;
        const fillPct = clamp(((z.last_moisture - wp) / (fc - wp)) * 100, 0, 100);
        const thresholdPct = clamp(((z.low_threshold_pct - wp) / (fc - wp)) * 100, 0, 100);
        const stateLabel = { normal: "OK", irrigating: "Regando", low: "Lluvia" }[z.status] ?? "OK";
        const stateClass = { normal: "state-normal", irrigating: "state-irrigating", low: "state-low" }[z.status];

        return `
        <article class="zone-card">
            <header class="zone-header">
                <div class="zone-title">
                    <h3>${escapeHtml(z.node_id)}</h3>
                    <p>Cultivo: ${escapeHtml(z.crop || "—")}</p>
                </div>
                <span class="zone-state ${stateClass}">${stateLabel}</span>
            </header>
            <div class="moisture-visual">
                <div class="moisture-bar">
                    <div class="moisture-fill" style="height:${fillPct.toFixed(1)}%"></div>
                    <div class="moisture-threshold" style="bottom:${thresholdPct.toFixed(1)}%">umbral</div>
                </div>
                <div class="moisture-readout">
                    <span class="moisture-value">${z.last_moisture?.toFixed(1) ?? "--"}</span>
                    <span class="moisture-unit">% humedad</span>
                </div>
            </div>
            <div class="zone-meta">
                <span><strong>Temp. suelo</strong> ${fmt(z.last_soil_temp, "°C")}</span>
                <span><strong>Temp. aire</strong> ${fmt(z.last_ambient_temp, "°C")}</span>
                <span><strong>Humedad aire</strong> ${fmt(z.last_ambient_humidity, "%")}</span>
                <span><strong>Batería</strong> ${fmt(z.battery_v, "V")}</span>
            </div>
        </article>`;
    }

    function renderDecisions() {
        el.decisionLog.innerHTML = state.decisions.map((d) => {
            const klass = d.decision === "irrigate"
                ? "irrigate"
                : (d.rationale && d.rationale.toLowerCase().includes("rain") ? "skip" : "hold");
            const tag = d.decision === "irrigate" ? "REGAR"
                      : klass === "skip" ? "SKIP"
                      : "HOLD";
            return `
            <li class="${klass}">
                <time>${shortTime(d.timestamp)}</time>
                <span class="tag ${klass}">${tag}</span>
                <span><strong>${escapeHtml(d.node_id)}</strong> — ${escapeHtml(d.rationale ?? "")}</span>
            </li>`;
        }).join("");
    }

    function renderEvents() {
        el.irrigationLog.innerHTML = state.events.map((e) => {
            const volume = e.volume_delivered_l ?? 0;
            const delta = (e.moisture_after ?? 0) - (e.moisture_before ?? 0);
            return `
            <li class="event">
                <time>${shortTime(e.observed_at || e.timestamp)}</time>
                <span class="tag event">RIEGO</span>
                <span><strong>${escapeHtml(e.node_id)}</strong> — +${delta.toFixed(1)}% humedad · ${volume.toFixed(1)} L · ${escapeHtml(e.reason ?? "")}</span>
            </li>`;
        }).join("");
    }

    function renderWeather() {
        if (!state.weather) {
            el.weatherBadge.textContent = "clima · —";
            return;
        }
        const { precipitation_mm_6h = 0, rain_probability = 0 } = state.weather;
        el.weatherBadge.textContent = `clima · ${precipitation_mm_6h.toFixed(1)} mm/6h · p=${(rain_probability * 100).toFixed(0)}%`;
    }

    async function injectRain() {
        el.injectRainBtn.disabled = true;
        el.injectRainBtn.textContent = "Enviando…";
        try {
            const response = await fetch(`${WEATHER_URL}/forecast`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    precipitation_mm_6h: 6.0,
                    rain_probability: 0.85,
                    duration_seconds: 180,
                }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            el.injectRainBtn.textContent = "Lluvia inyectada (3 min)";
            setTimeout(() => {
                el.injectRainBtn.disabled = false;
                el.injectRainBtn.textContent = "Inyectar pronóstico de lluvia";
            }, 3500);
        } catch (err) {
            el.injectRainBtn.textContent = `Error: ${err.message}`;
            setTimeout(() => {
                el.injectRainBtn.disabled = false;
                el.injectRainBtn.textContent = "Inyectar pronóstico de lluvia";
            }, 3500);
        }
    }

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function fmt(value, unit) {
        if (value === undefined || value === null || Number.isNaN(value)) return "—";
        return `${Number(value).toFixed(1)} ${unit}`;
    }

    function shortTime(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleTimeString("es-CO", { hour12: false });
        } catch (_) {
            return "—";
        }
    }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
        }[ch]));
    }
})();
