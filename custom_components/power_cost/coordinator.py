"""Calcolo di energia e costi dalla cronologia di un sensore di potenza."""

from __future__ import annotations

from bisect import bisect_right
import calendar
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
import logging
from typing import Any

from homeassistant.components.recorder import get_instance, history
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import PowerConverter

from .const import (
    CONF_FIXED_MONTHLY,
    CONF_POWER_ENTITY,
    CONF_PRICE_KWH,
    CONF_PRICES,
    CONF_VALID_FROM,
    DOMAIN,
    PERIOD_DAY,
    PERIOD_MONTH,
    PERIOD_QUARTER,
    PERIOD_TOTAL,
    PERIOD_WEEK,
    PERIOD_YEAR,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type PowerCostConfigEntry = ConfigEntry[PowerCostCoordinator]


@dataclass(frozen=True, slots=True)
class Price:
    """Tariffa in vigore da un certo giorno."""

    valid_from: date
    price_kwh: float
    fixed_monthly: float


class PriceSchedule:
    """Storico delle tariffe: ognuna vale dal suo giorno fino alla successiva."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.prices = sorted(
            (
                Price(
                    date.fromisoformat(entry[CONF_VALID_FROM]),
                    entry[CONF_PRICE_KWH],
                    entry[CONF_FIXED_MONTHLY],
                )
                for entry in entries
            ),
            key=lambda price: price.valid_from,
        )
        self._starts = [price.valid_from for price in self.prices]

    def at(self, day: date) -> Price:
        """Tariffa di un giorno; la prima vale anche per i giorni precedenti."""
        return self.prices[max(bisect_right(self._starts, day) - 1, 0)]

    def daily_fixed(self, day: date) -> float:
        """Quota fissa di un giorno: quota mensile divisa per i giorni del mese."""
        return self.at(day).fixed_monthly / calendar.monthrange(day.year, day.month)[1]


@dataclass(frozen=True, slots=True)
class PeriodData:
    """Consumi e costi di un periodo, dal primo giorno con dati a oggi."""

    data_start: date
    energy_kwh: float
    energy_cost: float
    fixed_cost: float
    projected_cost: float | None

    @property
    def cost(self) -> float:
        return self.energy_cost + self.fixed_cost


@dataclass(frozen=True, slots=True)
class PowerCostData:
    periods: dict[str, PeriodData]


class PowerCostCoordinator(DataUpdateCoordinator[PowerCostData]):
    """Legge le statistiche orarie del sensore di potenza e ne calcola i costi.

    Le ore già compilate nelle statistiche a lungo termine (conservate per
    sempre) danno lo storico; l'ultima ora non ancora compilata viene integrata
    dagli stati registrati.
    """

    config_entry: PowerCostConfigEntry

    def __init__(self, hass: HomeAssistant, entry: PowerCostConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.power_entity: str = entry.data[CONF_POWER_ENTITY]
        self.prices = PriceSchedule(entry.options[CONF_PRICES])
        # kWh per giorno locale dalle statistiche orarie già lette
        self._daily_energy: defaultdict[date, float] = defaultdict(float)
        # Fine dell'ultima ora letta dalle statistiche
        self._stats_end: datetime | None = None

    async def _async_update_data(self) -> PowerCostData:
        now = dt_util.utcnow()
        await self._async_load_statistics(now)
        daily = dict(self._daily_energy)
        for day, kwh in (await self._async_recent_energy(now)).items():
            daily[day] = daily.get(day, 0.0) + kwh
        return self._compute(daily)

    async def _async_load_statistics(self, now: datetime) -> None:
        """Aggiunge le ore compilate dopo l'ultima lettura (alla prima, tutto lo storico)."""
        start = self._stats_end or dt_util.utc_from_timestamp(0)
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            now,
            {self.power_entity},
            "hour",
            {"power": UnitOfPower.KILO_WATT},
            {"mean"},
        )
        for row in stats.get(self.power_entity, []):
            self._stats_end = dt_util.utc_from_timestamp(row["end"])
            if (mean := row.get("mean")) is not None:
                day = dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date()
                # Potenza media in kW su un'ora = kWh consumati in quell'ora
                self._daily_energy[day] += mean

    async def _async_recent_energy(self, now: datetime) -> dict[date, float]:
        """Integra gli stati registrati dopo l'ultima ora presente nelle statistiche."""
        start = self._stats_end or now.replace(minute=0, second=0, microsecond=0)
        states = (
            await get_instance(self.hass).async_add_executor_job(
                partial(
                    history.state_changes_during_period,
                    self.hass,
                    start,
                    now,
                    self.power_entity,
                    no_attributes=True,
                    include_start_time_state=True,
                )
            )
        ).get(self.power_entity, [])
        current = self.hass.states.get(self.power_entity)
        if not states and current is not None:
            states = [current]
        unit = current.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if current else None

        energy: defaultdict[date, float] = defaultdict(float)
        for state, next_state in zip(states, [*states[1:], None]):
            _add_energy(
                energy,
                max(state.last_changed, start),
                next_state.last_changed if next_state else now,
                _to_kw(state.state, unit),
            )
        return energy

    def _compute(self, daily: dict[date, float]) -> PowerCostData:
        now = dt_util.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)
        first_day = min(daily, default=today)

        bounds: dict[str, tuple[date, date | None]] = {
            **_period_bounds(today),
            PERIOD_TOTAL: (first_day, None),
        }
        periods: dict[str, PeriodData] = {}
        for period, (start, end) in bounds.items():
            data_start = max(start, first_day)
            energy = energy_cost = 0.0
            for day, kwh in daily.items():
                if day >= data_start:
                    energy += kwh
                    energy_cost += kwh * self.prices.at(day).price_kwh
            fixed_cost = sum(
                self.prices.daily_fixed(day) for day in _days(data_start, tomorrow)
            )

            projected_cost = None
            elapsed = now - dt_util.start_of_local_day(data_start)
            if end is not None and elapsed >= timedelta(hours=1):
                # Consumo medio finora esteso a tutto il periodo + quota fissa intera
                length = dt_util.start_of_local_day(end) - dt_util.start_of_local_day(
                    start
                )
                projected_cost = energy_cost * (length / elapsed) + sum(
                    self.prices.daily_fixed(day) for day in _days(start, end)
                )

            periods[period] = PeriodData(
                data_start, energy, energy_cost, fixed_cost, projected_cost
            )
        return PowerCostData(periods)


def _period_bounds(today: date) -> dict[str, tuple[date, date]]:
    """Inizio (incluso) e fine (esclusa) dei periodi che contengono oggi."""
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    quarter = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
    year = date(today.year, 1, 1)
    return {
        PERIOD_DAY: (today, today + timedelta(days=1)),
        PERIOD_WEEK: (week, week + timedelta(days=7)),
        PERIOD_MONTH: (month, _add_months(month, 1)),
        PERIOD_QUARTER: (quarter, _add_months(quarter, 3)),
        PERIOD_YEAR: (year, date(today.year + 1, 1, 1)),
    }


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    return date(day.year + month // 12, month % 12 + 1, 1)


def _days(start: date, end: date) -> Iterator[date]:
    day = start
    while day < end:
        yield day
        day += timedelta(days=1)


def _add_energy(
    energy: defaultdict[date, float], start: datetime, end: datetime, power_kw: float
) -> None:
    """Aggiunge l'energia di un intervallo a potenza costante, divisa per giorno locale."""
    while start < end:
        day = dt_util.as_local(start).date()
        split = min(end, dt_util.start_of_local_day(day + timedelta(days=1)))
        energy[day] += power_kw * (split - start).total_seconds() / 3600
        start = split


def _to_kw(value: str, unit: str | None) -> float:
    """Converte uno stato in kW; unavailable/unknown valgono 0."""
    try:
        power = float(value)
    except ValueError:
        return 0.0
    try:
        return PowerConverter.convert(power, unit or UnitOfPower.WATT, UnitOfPower.KILO_WATT)
    except HomeAssistantError:
        return power / 1000
