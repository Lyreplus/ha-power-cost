"""Sensori di costo per periodo e di energia totale."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PERIOD_TOTAL, PERIODS
from .coordinator import PowerCostConfigEntry, PowerCostCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerCostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(PowerCostSensor(coordinator, period) for period in PERIODS),
            PowerCostEnergySensor(coordinator),
        ]
    )


class PowerCostEntity(CoordinatorEntity[PowerCostCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PowerCostCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )


class PowerCostSensor(PowerCostEntity, SensorEntity):
    """Costo del periodo corrente: energia consumata + quota fissa maturata."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: PowerCostCoordinator, period: str) -> None:
        super().__init__(coordinator, f"cost_{period}")
        self._period = period
        self._attr_native_unit_of_measurement = coordinator.hass.config.currency

    @property
    def native_value(self) -> float:
        return round(self.coordinator.data.periods[self._period].cost, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.periods[self._period]
        price = self.coordinator.prices.at(dt_util.now().date())
        attrs: dict[str, Any] = {
            "energy_kwh": round(data.energy_kwh, 3),
            "energy_cost": round(data.energy_cost, 2),
            "fixed_cost": round(data.fixed_cost, 2),
            "data_since": data.data_start.isoformat(),
            "price_kwh": price.price_kwh,
            "fixed_monthly": price.fixed_monthly,
        }
        if data.projected_cost is not None:
            attrs["projected_cost"] = round(data.projected_cost, 2)
        return attrs


class PowerCostEnergySensor(PowerCostEntity, SensorEntity):
    """Energia totale consumata, utilizzabile nella dashboard Energia."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: PowerCostCoordinator) -> None:
        super().__init__(coordinator, "energy_total")
        self._max: float = 0.0

    @property
    def native_value(self) -> float:
        # Quando un'ora passa dalla stima alle statistiche il totale può calare
        # di poco: non lo facciamo scendere, altrimenti conterebbe come azzeramento.
        self._max = max(
            self._max, self.coordinator.data.periods[PERIOD_TOTAL].energy_kwh
        )
        return round(self._max, 3)
