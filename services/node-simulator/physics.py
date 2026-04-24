"""Soil moisture dynamics for a single AgroSmart field node.

The model is deliberately simple yet qualitatively faithful:

    dtheta/dt = - ET(T, RH) + R(rain) + I(irrigation)

where theta is volumetric soil moisture expressed as percent between the
wilting point and field capacity. Evapotranspiration follows a reduced
Penman-Monteith heuristic parameterised by ambient temperature and humidity;
rainfall and irrigation add water at constant rates bounded by capacity.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class SoilProfile:
    crop: str
    field_capacity_pct: float
    wilting_point_pct: float
    et_max_mm_per_hour: float = 0.35


@dataclass
class AmbientState:
    temp_c: float
    humidity_pct: float
    raining: bool = False


class SoilState:
    """Evolves soil moisture over simulated time.

    Irrigation is applied by `irrigate(volume_equivalent_pct)`, which adds
    a bounded amount of moisture capped by field capacity.
    """

    def __init__(self, profile: SoilProfile, initial_moisture_pct: float):
        self.profile = profile
        self.moisture_pct = float(initial_moisture_pct)
        self.soil_temp_c = 18.0

    def step(self, ambient: AmbientState, sim_dt_seconds: float) -> None:
        hours = sim_dt_seconds / 3600.0

        et_rate = self._evapotranspiration_rate(ambient)
        rain_rate = 8.0 if ambient.raining else 0.0

        delta_pct = (rain_rate - et_rate) * hours
        self.moisture_pct = self._clamp(self.moisture_pct + delta_pct)

        self.soil_temp_c += (ambient.temp_c - self.soil_temp_c) * min(1.0, hours * 0.25)
        self.soil_temp_c += random.gauss(0, 0.08)

    def irrigate(self, volume_equivalent_pct: float) -> float:
        before = self.moisture_pct
        self.moisture_pct = self._clamp(self.moisture_pct + volume_equivalent_pct)
        return self.moisture_pct - before

    def _evapotranspiration_rate(self, ambient: AmbientState) -> float:
        temp_factor = max(0.0, (ambient.temp_c - 10.0) / 20.0)
        humidity_factor = max(0.1, 1.0 - ambient.humidity_pct / 100.0)
        moisture_factor = max(0.1, (self.moisture_pct - self.profile.wilting_point_pct)
                              / max(1.0, self.profile.field_capacity_pct - self.profile.wilting_point_pct))
        return self.profile.et_max_mm_per_hour * temp_factor * humidity_factor * moisture_factor

    def _clamp(self, value: float) -> float:
        return max(self.profile.wilting_point_pct,
                   min(self.profile.field_capacity_pct, value))


def diurnal_ambient(sim_epoch_seconds: float,
                    base_temp_c: float = 19.0,
                    temp_amplitude_c: float = 8.0,
                    base_humidity_pct: float = 65.0,
                    humidity_amplitude_pct: float = 20.0,
                    rain_prob_per_hour: float = 0.04) -> AmbientState:
    """Approximate a diurnal cycle for temperature and humidity.

    A full sine period lasts one simulated day. Rain is a low-probability
    Bernoulli event sampled at the simulation cadence.
    """
    day_phase = (sim_epoch_seconds % 86400.0) / 86400.0
    angle = 2.0 * math.pi * (day_phase - 0.25)

    temp = base_temp_c + temp_amplitude_c * math.sin(angle) + random.gauss(0, 0.4)
    humidity = base_humidity_pct - humidity_amplitude_pct * math.sin(angle) + random.gauss(0, 1.5)
    humidity = max(15.0, min(98.0, humidity))

    raining = random.random() < rain_prob_per_hour / 60.0
    return AmbientState(temp_c=temp, humidity_pct=humidity, raining=raining)
