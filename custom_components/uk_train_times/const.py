"""Constants for the UK Train Times integration."""

from datetime import time

DOMAIN = "uk_train_times"

# RTT API Configuration
RTT_API_BASE_URL = "https://data.rtt.io"
RTT_API_VERSION = "v1"

MAX_TIME_OFFSET = 120

CONF_HOURS_OF_INTEREST = "hours_of_interest"
CONF_START_TIME = "start_time"
CONF_END_TIME = "end_time"

DEFAULT_START_TIME = time(6, 0)
DEFAULT_END_TIME = time(0, 0)
