"""Constants for the Tranzy integration."""

from datetime import timedelta
import logging

DOMAIN = "tranzy"
LOGGER = logging.getLogger(__package__)

API_BASE = "https://api.tranzy.ai/v1/opendata"

CONF_AGENCY_ID = "agency_id"
CONF_STOP_ID = "stop_id"
CONF_STOP_NAME = "stop_name"
SUBENTRY_STOP = "stop"

# Options
CONF_SPEED = "speed_kmh"
CONF_LAYOVER = "layover_min"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_AGE = "max_age_min"

# Both fitted on 239 593 predictions against 13 124 real arrivals in Chișinău
# (2026-11-02, 16:00-17:30) with script/accuracy.py: 13.1 km/h and 2.5 min
# at the rush hour, rounded towards the rest of the day.
DEFAULT_SPEED = 14.0  # km/h, average incl. stops and lights
DEFAULT_LAYOVER = 4  # min at the terminus before the return trip
DEFAULT_SCAN_INTERVAL = 30  # s; 2880 requests/day of a 5000/day quota
DEFAULT_MAX_AGE = 5  # min; older vehicle positions are dropped

STATIC_TTL = timedelta(hours=24)
HORIZON = timedelta(minutes=60)
MAX_ARRIVALS = 20

CARD_URL = "/tranzy_static/tranzy-board-card.js"
