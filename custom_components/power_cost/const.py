"""Costanti dell'integrazione Power Cost."""

from datetime import timedelta

DOMAIN = "power_cost"

CONF_POWER_ENTITY = "power_entity"
CONF_PRICE_KWH = "price_kwh"
CONF_FIXED_MONTHLY = "fixed_monthly"
CONF_VALID_FROM = "valid_from"
CONF_APPLY_TO_ALL = "apply_to_all"
CONF_PRICES = "prices"

# Data di validità del primo prezzo: vale per tutto lo storico disponibile
HISTORY_START = "1970-01-01"

UPDATE_INTERVAL = timedelta(minutes=1)

PERIOD_DAY = "day"
PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIOD_QUARTER = "quarter"
PERIOD_YEAR = "year"
PERIOD_TOTAL = "total"
PERIODS = (
    PERIOD_DAY,
    PERIOD_WEEK,
    PERIOD_MONTH,
    PERIOD_QUARTER,
    PERIOD_YEAR,
    PERIOD_TOTAL,
)
