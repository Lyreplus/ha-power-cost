"""Test di Power Cost."""

from datetime import date, datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.power_cost.const import (
    CONF_APPLY_TO_ALL,
    CONF_FIXED_MONTHLY,
    CONF_POWER_ENTITY,
    CONF_PRICE_KWH,
    CONF_PRICES,
    CONF_VALID_FROM,
    DOMAIN,
    HISTORY_START,
)
from custom_components.power_cost.coordinator import PriceSchedule

POWER = "sensor.presa_power"
POWER_ATTRS = {
    "unit_of_measurement": "W",
    "device_class": "power",
    "state_class": "measurement",
}


def _prices(*entries: tuple[str, float, float]) -> list[dict]:
    return [
        {CONF_VALID_FROM: d, CONF_PRICE_KWH: p, CONF_FIXED_MONTHLY: f}
        for d, p, f in entries
    ]


def test_price_schedule() -> None:
    schedule = PriceSchedule(
        _prices(("2026-10-10", 0.30, 10.0), (HISTORY_START, 0.20, 31.0))
    )
    assert schedule.at(date(2020, 1, 1)).price_kwh == 0.20
    assert schedule.at(date(2026, 10, 9)).price_kwh == 0.20
    assert schedule.at(date(2026, 10, 10)).price_kwh == 0.30
    # Ottobre ha 31 giorni, febbraio 2026 ne ha 28
    assert schedule.daily_fixed(date(2026, 10, 1)) == pytest.approx(31 / 31)
    assert schedule.daily_fixed(date(2026, 10, 20)) == pytest.approx(10 / 31)
    assert schedule.daily_fixed(date(2026, 2, 1)) == pytest.approx(31 / 28)


async def test_config_flow(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    hass.states.async_set(POWER, "50", POWER_ATTRS)
    hass.states.async_set("sensor.no_stats", "50", {"unit_of_measurement": "W"})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    user_input = {
        "name": "Presa",
        CONF_POWER_ENTITY: "sensor.no_stats",
        CONF_PRICE_KWH: 0.25,
        CONF_FIXED_MONTHLY: 10,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["errors"] == {CONF_POWER_ENTITY: "no_statistics"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**user_input, CONF_POWER_ENTITY: POWER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Presa"
    assert result["data"] == {CONF_POWER_ENTITY: POWER}
    assert result["options"] == {CONF_PRICES: _prices((HISTORY_START, 0.25, 10))}


async def test_options_flow(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POWER_ENTITY: POWER},
        options={
            CONF_PRICES: _prices(
                (HISTORY_START, 0.20, 10), ("2026-09-01", 0.22, 10), ("2026-10-01", 0.24, 10)
            )
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PRICE_KWH: 0.30,
            CONF_FIXED_MONTHLY: 12,
            CONF_VALID_FROM: "2026-09-15",
            CONF_APPLY_TO_ALL: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # La tariffa di ottobre parte dopo il 15/09: viene sostituita
    assert entry.options[CONF_PRICES] == _prices(
        (HISTORY_START, 0.20, 10), ("2026-09-01", 0.22, 10), ("2026-09-15", 0.30, 12)
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PRICE_KWH: 0.18,
            CONF_FIXED_MONTHLY: 8,
            CONF_VALID_FROM: "2026-10-21",
            CONF_APPLY_TO_ALL: True,
        },
    )
    assert entry.options[CONF_PRICES] == _prices((HISTORY_START, 0.18, 8))


async def test_costs_from_history(
    recorder_mock: Recorder, hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Statistiche orarie dal 20/10 alle 12:00 del 21/10, poi mezz'ora di stati."""
    await hass.config.async_set_time_zone("Europe/Rome")
    first_hour = dt_util.as_utc(datetime(2026, 10, 20, tzinfo=dt_util.get_default_time_zone()))
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name=None,
            source="recorder",
            statistic_id=POWER,
            unit_class="power",
            unit_of_measurement="W",
        ),
        [
            StatisticData(
                start=first_hour + timedelta(hours=h), mean=100, min=100, max=100
            )
            for h in range(36)
        ],
    )

    noon = first_hour + timedelta(hours=36)
    freezer.move_to(noon)
    hass.states.async_set(POWER, "100", POWER_ATTRS)
    await async_wait_recording_done(hass)
    freezer.move_to(noon + timedelta(minutes=30))

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Presa",
        data={CONF_POWER_ENTITY: POWER},
        # 31 €/mese a ottobre = 1 €/giorno
        options={CONF_PRICES: _prices((HISTORY_START, 0.25, 31))},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)

    def state(key: str):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        return hass.states.get(entity_id)

    # Oggi: 12 ore da statistiche + 30 minuti da stati, a 0,1 kW
    today = state("cost_day")
    assert today.attributes["energy_kwh"] == pytest.approx(1.25)
    assert float(today.state) == pytest.approx(1.25 * 0.25 + 1)
    # Proiezione: 0,3125 € in 12,5 h -> 24 h, più 1 € di quota fissa
    assert today.attributes["projected_cost"] == pytest.approx(0.3125 * 24 / 12.5 + 1, abs=0.01)

    # La settimana inizia lunedì 19/10 ma i dati partono dal 20/10
    week = state("cost_week")
    assert week.attributes["data_since"] == "2026-10-20"
    assert week.attributes["energy_kwh"] == pytest.approx(3.65)
    assert float(week.state) == pytest.approx(3.65 * 0.25 + 2)

    assert float(state("cost_total").state) == pytest.approx(3.65 * 0.25 + 2)
    assert float(state("energy_total").state) == pytest.approx(3.65)

    # Un nuovo aggiornamento legge solo le statistiche nuove: niente doppi conteggi
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(state("energy_total").state) == pytest.approx(3.65)
    assert state("cost_total").attributes["energy_kwh"] == pytest.approx(3.65)
