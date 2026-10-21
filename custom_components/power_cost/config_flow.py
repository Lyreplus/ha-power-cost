"""Configurazione dall'interfaccia: sensore di potenza e tariffe."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import (
    ATTR_STATE_CLASS,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APPLY_TO_ALL,
    CONF_FIXED_MONTHLY,
    CONF_POWER_ENTITY,
    CONF_PRICE_KWH,
    CONF_PRICES,
    CONF_VALID_FROM,
    DOMAIN,
    HISTORY_START,
)
from .coordinator import PriceSchedule


def _price_fields(currency: str) -> dict[vol.Marker, Any]:
    return {
        vol.Required(CONF_PRICE_KWH): NumberSelector(
            NumberSelectorConfig(
                min=0,
                step="any",
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=f"{currency}/kWh",
            )
        ),
        vol.Required(CONF_FIXED_MONTHLY, default=0): NumberSelector(
            NumberSelectorConfig(
                min=0,
                step=0.01,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=currency,
            )
        ),
    }


class PowerCostConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entity_id = user_input[CONF_POWER_ENTITY]
            self._async_abort_entries_match({CONF_POWER_ENTITY: entity_id})
            state = self.hass.states.get(entity_id)
            if state is None:
                errors[CONF_POWER_ENTITY] = "entity_not_found"
            elif state.attributes.get(ATTR_STATE_CLASS) != SensorStateClass.MEASUREMENT:
                # Senza state_class measurement non ci sono statistiche a lungo termine
                errors[CONF_POWER_ENTITY] = "no_statistics"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_POWER_ENTITY: entity_id},
                    options={
                        CONF_PRICES: [
                            {
                                CONF_VALID_FROM: HISTORY_START,
                                CONF_PRICE_KWH: user_input[CONF_PRICE_KWH],
                                CONF_FIXED_MONTHLY: user_input[CONF_FIXED_MONTHLY],
                            }
                        ]
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_POWER_ENTITY): EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor", device_class=SensorDeviceClass.POWER
                    )
                ),
                **_price_fields(self.hass.config.currency),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PowerCostOptionsFlow:
        return PowerCostOptionsFlow()


class PowerCostOptionsFlow(OptionsFlow):
    """Nuova tariffa valida da una data: lo storico precedente resta invariato."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        prices: list[dict[str, Any]] = self.config_entry.options[CONF_PRICES]
        if user_input is not None:
            valid_from = (
                HISTORY_START
                if user_input[CONF_APPLY_TO_ALL]
                else user_input[CONF_VALID_FROM]
            )
            # La nuova tariffa sostituisce quelle che partono dalla stessa data o dopo
            new_prices = [p for p in prices if p[CONF_VALID_FROM] < valid_from]
            new_prices.append(
                {
                    CONF_VALID_FROM: valid_from,
                    CONF_PRICE_KWH: user_input[CONF_PRICE_KWH],
                    CONF_FIXED_MONTHLY: user_input[CONF_FIXED_MONTHLY],
                }
            )
            return self.async_create_entry(data={CONF_PRICES: new_prices})

        currency = self.hass.config.currency
        today = dt_util.now().date()
        schedule = PriceSchedule(prices)
        current = schedule.at(today)
        history = "\n".join(
            f"- {'inizio' if p.valid_from.isoformat() == HISTORY_START else p.valid_from}: "
            f"{p.price_kwh} {currency}/kWh + {p.fixed_monthly} {currency}/mese"
            for p in schedule.prices
        )
        schema = vol.Schema(
            {
                **_price_fields(currency),
                vol.Required(CONF_VALID_FROM): DateSelector(),
                vol.Required(CONF_APPLY_TO_ALL, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_PRICE_KWH: current.price_kwh,
                    CONF_FIXED_MONTHLY: current.fixed_monthly,
                    CONF_VALID_FROM: today.isoformat(),
                },
            ),
            description_placeholders={"history": history},
        )
