# AgroSmart — Digital Twin (Prototipo de bajo nivel)

Proyecto de Ingeniería I · 202337120A_2201 · UNAD ECBTI · Grupo 302
Autor del prototipo individual: Andrés Camilo Briñez Núñez

[**Ver demostración en video (YouTube · 4 min)**](https://youtu.be/0bhDaJdJU0A)

Este prototipo materializa de manera **digital** el diseño de AgroSmart
construido en la Etapa 3: un sistema de riego inteligente de bajo costo
con nodos de campo autónomos, un coordinador central con datos
climáticos y una red de goteo controlada por electroválvulas. Cada
componente del diseño se implementa como un servicio aislado dentro de
un *stack* orquestado con Docker, de modo que una única instrucción
(`docker compose up -d`) levanta un gemelo digital ejecutable del
sistema completo.

---

## 1. Arquitectura del gemelo

| Componente real (Etapa 3)         | Servicio del *stack*                        | Tecnología                    |
|-----------------------------------|----------------------------------------------|-------------------------------|
| Nodo ESP32 + sensores + LoRa      | `node-zone-1`, `node-zone-2`, `node-zone-3` | Python 3.12 · paho-mqtt       |
| Red de comunicación LoRa          | `mosquitto`                                  | Eclipse Mosquitto 2.0 (MQTT)  |
| Coordinador central (ESP32+WiFi)  | `coordinator`                                | Python 3.12 · httpx           |
| Consulta a API meteorológica      | `weather-mock`                               | FastAPI + Uvicorn             |
| Electroválvulas y confirmación    | `actuator`                                   | Python 3.12 · paho-mqtt       |
| Persistencia de series temporales | `timescaledb`                                | TimescaleDB (PostgreSQL 15)   |
| Dashboard Grafana                 | `grafana`                                    | Grafana 10.4                  |
| Panel operador (HMI)              | `web-ui`                                     | Nginx · HTML · JS · MQTT.js   |
| Puente MQTT → base de datos       | `telemetry-ingestor`                         | Python 3.12 · psycopg 3       |

Los mensajes entre nodos y coordinador siguen el esquema:

```
agrosmart/telemetry/node/{zone}           ← lecturas de sensores
agrosmart/commands/node/{zone}/irrigate   ← órdenes de riego
agrosmart/events/actuator/{zone}          ← confirmación de la válvula
agrosmart/decisions/node/{zone}           ← decisiones del coordinador
agrosmart/status/coordinator              ← heartbeat y perfiles por zona
```

### 1.1 Modelo físico de los nodos

Cada nodo simulado integra un modelo de dinámica de humedad del suelo:

```
θ(t+Δt) = clamp( θ(t) − ET(T, RH) · Δt + R_lluvia · Δt + I_riego,
                 punto_marchitez, capacidad_campo )
```

donde `ET` es una heurística reducida de Penman–Monteith parametrizada
por temperatura y humedad ambiente; `R_lluvia` se activa con probabilidad
diurna, e `I_riego` responde a los comandos del coordinador. El tiempo
simulado avanza a la velocidad configurada en `AGROSMART_TIME_SCALE`
(por defecto 60× el tiempo real, es decir, un día simulado cada 24 min
reales).

### 1.2 Política de decisión del coordinador

El coordinador mantiene un perfil por zona con tres parámetros:
capacidad de campo, punto de marchitez y umbral bajo adaptativo. Cada
telemetría actualiza un promedio exponencial (EWMA) del nivel de
humedad; cuando la humedad observada cae por debajo del umbral y el
pronóstico de lluvia en 6 h no supera `rain_skip_threshold_mm`, se
publica un comando `irrigate` con la duración calculada a partir del
déficit actual.

---

## 2. Puertos y aislamiento

El *stack* usa un rango de puertos no estándar y un nombre de proyecto
dedicado (`agrosmart`) para no interferir con otros contenedores en
ejecución. Todos los puertos son configurables en `.env`:

| Servicio                   | Puerto host (por defecto) |
|----------------------------|---------------------------|
| Grafana                    | `3333`                    |
| Panel operador (web-ui)    | `8095`                    |
| Weather mock (FastAPI)     | `8096`                    |
| MQTT (broker TCP)          | `18830`                   |
| MQTT (WebSockets)          | `18831`                   |
| TimescaleDB                | `54329`                   |

Los volúmenes `agrosmart_timescale_data`, `agrosmart_grafana_data` y
`agrosmart_mosquitto_data` llevan prefijo explícito y no chocan con
volúmenes existentes en la máquina.

---

## 3. Puesta en marcha

Desde el directorio `prototipo_acb/`:

```bash
cp .env.example .env      # ajustar puertos o credenciales si se desea
docker compose build      # compilar imágenes de los servicios Python
docker compose up -d      # levantar el stack completo
docker compose ps         # verificar estado
```

Una vez en ejecución:

- Panel operador: <http://localhost:8095>
- Grafana (admin/admin): <http://localhost:3333> → carpeta *AgroSmart*
- API del mock de clima: <http://localhost:8096/docs>

Para detener todo sin borrar datos:

```bash
docker compose stop
```

Para apagar y borrar únicamente los recursos de este proyecto
(volúmenes y red creados por este compose), sin afectar nada más:

```bash
docker compose down -v
```

---

## 4. Guion de demostración (8 minutos)

1. **Estado estacionario.** Abrir el panel operador. Las tres zonas
   publican telemetría cada 15 minutos simulados. La humedad decae según
   el modelo físico.
2. **Primer ciclo de riego.** En pocos minutos reales, la zona 2
   (tomate, con humedad inicial baja) cruza el umbral. El coordinador
   emite `irrigate`, el nodo aplica el aporte y la barra sube.
3. **Inyección de lluvia.** Pulsar *Inyectar pronóstico de lluvia*.
   El coordinador cambia a decisiones `skip_rain` durante 3 minutos
   reales. La tarjeta de la zona pasa a estado *Lluvia*.
4. **Grafana en vivo.** Abrir `http://localhost:3333` → dashboard
   *AgroSmart — Vista Operacional*. Mostrar las gráficas históricas y
   las tablas de decisiones y eventos.
5. **Persistencia.** `docker compose stop` seguido de
   `docker compose up -d` demuestra que TimescaleDB conserva la
   serie temporal completa.

---

## 5. Mapeo con la rúbrica de la Etapa 4

| Criterio de la rúbrica          | Evidencia en este prototipo                                |
|---------------------------------|------------------------------------------------------------|
| Fidelidad al diseño original    | Cada servicio replica un bloque de la Figura 3 (Etapa 3).  |
| Funcionalidad                   | Ciclo completo sensado → decisión → riego observable.      |
| Calidad y profesionalismo       | Compose, tests implícitos, logs estructurados, README.     |
| Creatividad e innovación        | Gemelo digital con física realista y HMI en vivo.          |
| Ética y escalabilidad           | Modo de ahorro por pronóstico de lluvia + EWMA adaptativa. |

---

## 6. Estructura del repositorio

```
prototipo_acb/
├── docker-compose.yml
├── .env.example
├── README.md
├── services/
│   ├── node-simulator/        (Python · modelo físico ET + MQTT)
│   ├── coordinator/           (Python · motor de decisión + clima)
│   ├── actuator/              (Python · observador de válvulas)
│   ├── weather-mock/          (FastAPI · API de clima determinista)
│   ├── telemetry-ingestor/    (Python · MQTT → TimescaleDB)
│   └── web-ui/                (Nginx · HMI HTML+JS+MQTT.js)
├── mosquitto/config/
├── timescaledb/init.sql
├── grafana/
│   ├── provisioning/
│   └── dashboards/agrosmart.json
└── docs/
    ├── guion_video.md
    └── screenshots/
```

---

## 7. Licencia

Código liberado bajo licencia MIT. Ver [LICENSE](LICENSE).
