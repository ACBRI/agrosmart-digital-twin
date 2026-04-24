"""Irrigation decision logic for the AgroSmart coordinator.

Implements the hybrid policy described in the Etapa 3 design: each node
stores a crop-specific threshold, the coordinator overrides the decision
when rainfall is forecast, and adapts thresholds slowly from observed
moisture history (EWMA) so that each zone self-tunes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ZoneProfile:
    node_id: str
    crop: str
    field_capacity_pct: float
    wilting_point_pct: float
    low_threshold_pct: float
    target_pct: float
    moisture_ewma: Optional[float] = None
    last_action: Optional[str] = None


@dataclass
class WeatherSnapshot:
    precipitation_mm_6h: float
    rain_probability: float


@dataclass
class Decision:
    should_irrigate: bool
    rationale: str
    target_pct: float
    duration_s: int
    weather: Dict[str, float] = field(default_factory=dict)


class DecisionEngine:
    """Pure, testable policy — no I/O, no globals."""

    def __init__(self,
                 global_low_pct: float = 35.0,
                 global_target_pct: float = 70.0,
                 rain_skip_threshold_mm: float = 2.0,
                 rain_skip_probability: float = 0.6,
                 ewma_alpha: float = 0.2):
        self.global_low_pct = global_low_pct
        self.global_target_pct = global_target_pct
        self.rain_skip_threshold_mm = rain_skip_threshold_mm
        self.rain_skip_probability = rain_skip_probability
        self.ewma_alpha = ewma_alpha
        self.zones: Dict[str, ZoneProfile] = {}

    def register_zone(self, node_id: str, crop: str,
                      field_capacity_pct: float, wilting_point_pct: float) -> ZoneProfile:
        zone = self.zones.get(node_id)
        if zone is None:
            low = max(wilting_point_pct + 5, self.global_low_pct)
            target = min(field_capacity_pct - 2, self.global_target_pct)
            zone = ZoneProfile(
                node_id=node_id,
                crop=crop,
                field_capacity_pct=field_capacity_pct,
                wilting_point_pct=wilting_point_pct,
                low_threshold_pct=low,
                target_pct=target,
            )
            self.zones[node_id] = zone
        return zone

    def evaluate(self, node_id: str, current_moisture_pct: float,
                 weather: WeatherSnapshot) -> Decision:
        zone = self.zones[node_id]
        self._update_ewma(zone, current_moisture_pct)

        if current_moisture_pct >= zone.low_threshold_pct:
            return Decision(
                should_irrigate=False,
                rationale=f"moisture {current_moisture_pct:.1f}% at or above threshold "
                          f"{zone.low_threshold_pct:.1f}%",
                target_pct=zone.target_pct,
                duration_s=0,
                weather={
                    "precipitation_mm_6h": weather.precipitation_mm_6h,
                    "rain_probability": weather.rain_probability,
                },
            )

        if self._rain_expected(weather):
            zone.last_action = "skipped_rain"
            return Decision(
                should_irrigate=False,
                rationale=f"rain forecast (p={weather.rain_probability:.2f}, "
                          f"precip={weather.precipitation_mm_6h:.1f}mm) — skip irrigation",
                target_pct=zone.target_pct,
                duration_s=0,
                weather={
                    "precipitation_mm_6h": weather.precipitation_mm_6h,
                    "rain_probability": weather.rain_probability,
                },
            )

        duration_s = self._irrigation_duration(zone, current_moisture_pct)
        zone.last_action = "irrigate"
        return Decision(
            should_irrigate=True,
            rationale=f"moisture {current_moisture_pct:.1f}% below threshold "
                      f"{zone.low_threshold_pct:.1f}%; no rain expected",
            target_pct=zone.target_pct,
            duration_s=duration_s,
            weather={
                "precipitation_mm_6h": weather.precipitation_mm_6h,
                "rain_probability": weather.rain_probability,
            },
        )

    def _update_ewma(self, zone: ZoneProfile, sample: float) -> None:
        if zone.moisture_ewma is None:
            zone.moisture_ewma = sample
        else:
            zone.moisture_ewma = self.ewma_alpha * sample + (1.0 - self.ewma_alpha) * zone.moisture_ewma

        drift = zone.moisture_ewma - zone.target_pct
        if drift < -10:
            zone.low_threshold_pct = min(zone.target_pct - 5, zone.low_threshold_pct + 0.2)

    def _rain_expected(self, weather: WeatherSnapshot) -> bool:
        return (weather.precipitation_mm_6h >= self.rain_skip_threshold_mm
                and weather.rain_probability >= self.rain_skip_probability)

    def _irrigation_duration(self, zone: ZoneProfile, current: float) -> int:
        deficit_pct = max(0.0, zone.target_pct - current)
        base_seconds_per_pct = 60
        return int(max(180, min(1800, deficit_pct * base_seconds_per_pct)))
