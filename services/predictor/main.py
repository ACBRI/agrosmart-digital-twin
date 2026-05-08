"""Predictor service — AgroSmart group prototype.

Implements the predictive water-saving logic proposed by Wilson Steven
Rodríguez Castellanos in his individual prototype: a 7-day forward
projection of soil moisture under current ambient conditions and the
forecast for rain, comparing irrigation now vs. waiting and quantifying
the expected water saving versus a fixed-schedule baseline.

The coordinator queries this service through the HTTP endpoint
``GET /predict`` before deciding whether to irrigate. The aim is that
irrigation is only triggered when the predictive model confirms that
holding off would deplete the soil below the wilting point before the
next opportunity to wet the field.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI(title="AgroSmart Predictor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


WEATHER_URL = "http://weather-mock:8000"
HORIZON_HOURS = 24
SIMULATION_STEPS = 24
BASELINE_DAILY_LITERS = 40.0


@dataclass(frozen=True)
class WeatherForecast:
    precipitation_mm_6h: float
    rain_probability: float


class PredictionResponse(BaseModel):
    node_id: str
    recommendation: Literal["irrigate", "hold", "skip_rain"]
    rationale: str
    projected_moisture_in_24h_pct: float
    estimated_saving_pct: float
    weather: dict[str, float]


def _fetch_weather() -> WeatherForecast:
    try:
        response = httpx.get(f"{WEATHER_URL}/forecast", timeout=2.0)
        response.raise_for_status()
        data = response.json()
        return WeatherForecast(
            precipitation_mm_6h=float(data.get("precipitation_mm_6h", 0.0)),
            rain_probability=float(data.get("rain_probability", 0.0)),
        )
    except (httpx.HTTPError, ValueError):
        return WeatherForecast(0.0, 0.0)


def _evapotranspiration_per_hour(temp_c: float, humidity_pct: float) -> float:
    """Simplified Penman-Monteith heuristic (mm of soil moisture per hour).

    Higher temperature and lower ambient humidity drive larger losses.
    """
    temp_factor = max(0.0, (temp_c - 10.0) / 20.0)
    humidity_factor = max(0.1, 1.0 - humidity_pct / 100.0)
    return 0.35 * temp_factor * humidity_factor


def _project_moisture(initial_pct: float,
                      ambient_temp_c: float,
                      ambient_humidity_pct: float,
                      weather: WeatherForecast,
                      wilting_point_pct: float,
                      field_capacity_pct: float) -> float:
    """Forward simulation of soil moisture for HORIZON_HOURS hours.

    Mirrors the physical model of the field nodes but stops short of any
    irrigation event, so the projection answers: "if we DO NOT irrigate
    right now, where will the moisture end up in 24 h?".
    """
    moisture = initial_pct
    et = _evapotranspiration_per_hour(ambient_temp_c, ambient_humidity_pct)
    rain_probability = weather.rain_probability
    rain_per_hour = (weather.precipitation_mm_6h / 6.0) if weather.precipitation_mm_6h > 0 else 0.0

    dt = HORIZON_HOURS / SIMULATION_STEPS
    for step in range(SIMULATION_STEPS):
        rain_contribution = rain_per_hour * rain_probability if step < 6 else 0.0
        moisture += (rain_contribution - et) * dt
        moisture = max(wilting_point_pct, min(field_capacity_pct, moisture))
    return moisture


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/predict", response_model=PredictionResponse)
def predict(
    node_id: str = Query(...),
    moisture_pct: float = Query(...),
    ambient_temp_c: float = Query(...),
    ambient_humidity_pct: float = Query(...),
    low_threshold_pct: float = Query(35.0),
    target_pct: float = Query(70.0),
    wilting_point_pct: float = Query(20.0),
    field_capacity_pct: float = Query(72.0),
) -> PredictionResponse:
    weather = _fetch_weather()

    projected = _project_moisture(
        initial_pct=moisture_pct,
        ambient_temp_c=ambient_temp_c,
        ambient_humidity_pct=ambient_humidity_pct,
        weather=weather,
        wilting_point_pct=wilting_point_pct,
        field_capacity_pct=field_capacity_pct,
    )

    rain_expected = weather.precipitation_mm_6h >= 2.0 and weather.rain_probability >= 0.6

    if rain_expected:
        recommendation = "skip_rain"
        rationale = (
            f"forecast shows rain in next 6h (precip={weather.precipitation_mm_6h:.1f}mm, "
            f"p={weather.rain_probability:.2f}); projected moisture in 24h = {projected:.1f}%"
        )
    elif moisture_pct < low_threshold_pct or projected < wilting_point_pct + 5:
        recommendation = "irrigate"
        rationale = (
            f"current moisture {moisture_pct:.1f}% with projected drop to {projected:.1f}% "
            f"would breach safe margin above wilting point ({wilting_point_pct:.1f}%)"
        )
    else:
        recommendation = "hold"
        rationale = (
            f"projected moisture in 24h = {projected:.1f}%, comfortably above the "
            f"safe margin; no irrigation needed now"
        )

    saving = _baseline_saving(moisture_pct, projected, target_pct, recommendation)

    return PredictionResponse(
        node_id=node_id,
        recommendation=recommendation,
        rationale=rationale,
        projected_moisture_in_24h_pct=round(projected, 2),
        estimated_saving_pct=round(saving, 2),
        weather={
            "precipitation_mm_6h": weather.precipitation_mm_6h,
            "rain_probability": weather.rain_probability,
        },
    )


def _baseline_saving(current_pct: float,
                     projected_pct: float,
                     target_pct: float,
                     recommendation: str) -> float:
    """Estimated saving in percent versus a fixed-schedule daily irrigation.

    The baseline irrigation is `BASELINE_DAILY_LITERS` per node per day.
    If we hold or skip, we save 100% of that volume for the day. If we
    irrigate, we estimate the saving as the deficit avoided versus an
    over-irrigation event that would have wetted the soil up to field
    capacity (i.e. wasted water above the target).
    """
    if recommendation in ("hold", "skip_rain"):
        return 100.0
    deficit = max(0.0, target_pct - current_pct)
    over_irrigation = max(0.0, target_pct - projected_pct - deficit)
    if deficit + over_irrigation == 0:
        return 0.0
    return 100.0 * over_irrigation / (deficit + over_irrigation)
