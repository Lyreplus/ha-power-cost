"""Power Cost: costo dei consumi di un sensore di potenza."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import PowerCostConfigEntry, PowerCostCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: PowerCostConfigEntry) -> bool:
    coordinator = PowerCostCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # Le tariffe cambiano dalle opzioni: ricarica per ricalcolare i costi
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerCostConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: PowerCostConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
