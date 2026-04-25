"""Deterministic weather mock for the AgroSmart digital twin.

Exposes a minimal REST API that mimics OpenWeatherMap enough to drive
the coordinator. A rainfall event can be injected via POST /forecast
so that reviewers can reproduce the rain-skip scenario on demand.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


app = FastAPI(title="AgroSmart Weather Mock", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@dataclass
class State:
    injected_precipitation_mm: float = 0.0
    injected_probability: float = 0.0
    injected_until_epoch: float = 0.0
    epoch_start: float = field(default_factory=time.time)


state = State()


class ForecastInjection(BaseModel):
    precipitation_mm_6h: float = Field(ge=0.0, le=120.0)
    rain_probability: float = Field(ge=0.0, le=1.0)
    duration_seconds: int = Field(ge=30, le=3600)


class ForecastResponse(BaseModel):
    precipitation_mm_6h: float
    rain_probability: float
    synthetic: bool
    source: str


def _baseline() -> tuple[float, float]:
    hour_angle = 2 * math.pi * ((time.time() - state.epoch_start) / 600.0)
    wave = 0.5 + 0.5 * math.sin(hour_angle)
    precip = round(0.2 * wave, 3)
    prob = round(0.15 * wave, 3)
    return precip, prob


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/forecast", response_model=ForecastResponse)
def forecast() -> ForecastResponse:
    if time.time() < state.injected_until_epoch:
        return ForecastResponse(
            precipitation_mm_6h=state.injected_precipitation_mm,
            rain_probability=state.injected_probability,
            synthetic=True,
            source="injected",
        )
    precip, prob = _baseline()
    return ForecastResponse(
        precipitation_mm_6h=precip,
        rain_probability=prob,
        synthetic=True,
        source="baseline",
    )


@app.post("/forecast", response_model=ForecastResponse)
def inject(forecast: ForecastInjection) -> ForecastResponse:
    state.injected_precipitation_mm = forecast.precipitation_mm_6h
    state.injected_probability = forecast.rain_probability
    state.injected_until_epoch = time.time() + forecast.duration_seconds
    return ForecastResponse(
        precipitation_mm_6h=forecast.precipitation_mm_6h,
        rain_probability=forecast.rain_probability,
        synthetic=True,
        source="injected",
    )


@app.delete("/forecast")
def clear() -> dict[str, str]:
    state.injected_until_epoch = 0.0
    return {"status": "cleared"}
