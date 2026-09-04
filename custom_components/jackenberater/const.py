"""Constants for JackenBerater."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "jackenberater"
INTEGRATION_VERSION = "0.1.3"
PLATFORMS = ["sensor"]
PROFILE_BACKUP_ENABLED = False

CALENDAR_STATUS_AVAILABLE = "available"
CALENDAR_STATUS_NOT_CONFIGURED = "not_configured"
CALENDAR_STATUS_NOT_APPLICABLE = "not_applicable"
CALENDAR_STATUS_UNAVAILABLE = "unavailable"

CONF_WEATHER = "weather_entity"
CONF_INDOOR_TEMP = "indoor_temperature"
CONF_FALLBACK_INDOOR_TEMP = "fallback_indoor_temperature"
CONF_RAIN_ADVICE = "rain_advice"
CONF_CONTEXT_CALENDAR = "context_calendar_entity"
CONF_WORK_ZONE = "work_zone"
CONF_WORK_WEATHER = "work_weather_entity"
CONF_WORK_CALENDAR = "work_calendar_entity"  # legacy v0.1.0 key; no longer shown in UI
CONF_WORK_MODE = "work_mode"
CONF_WORKDAY_START = "workday_start"
CONF_WORKDAY_END = "workday_end"
CONF_VACATION_CALENDAR = "vacation_calendar_entity"
CONF_SHIFT_PATTERN = "shift_pattern"
CONF_SHIFT_ANCHOR_DATE = "shift_anchor_date"
CONF_SHIFT_EARLY_START = "shift_early_start"
CONF_SHIFT_EARLY_END = "shift_early_end"
CONF_SHIFT_LATE_START = "shift_late_start"
CONF_SHIFT_LATE_END = "shift_late_end"
CONF_SHIFT_NIGHT_START = "shift_night_start"
CONF_SHIFT_NIGHT_END = "shift_night_end"
CONF_SHARED_USER_IDS = "shared_user_ids"

SECTION_BASIC = "basic"
SECTION_CONTEXT = "context"
SECTION_WORK = "work"
SECTION_SHIFT = "shift"
SECTION_SHARED = "shared"

DEFAULT_FALLBACK_INDOOR_TEMP = 21.5
BASE_LIGHT_THRESHOLD_C = 18.0
BASE_WARM_THRESHOLD_C = 12.0
BASE_WINTER_THRESHOLD_C = 5.0
DEFAULT_WORKDAY_START = "08:00"
DEFAULT_WORKDAY_END = "17:00"

WORK_MODE_NONE = "none"
WORK_MODE_WEEKDAY = "weekday"
WORK_MODE_SHIFT = "shift"
WORK_MODES = (WORK_MODE_NONE, WORK_MODE_WEEKDAY, WORK_MODE_SHIFT)
DEFAULT_FORECAST_HOURS = 9
MAX_FORECAST_HOURS = 12
CALENDAR_MAX_HOURS = 16
WORK_BUFFER = timedelta(minutes=30)
FORECAST_REFRESH = timedelta(minutes=15)
SESSION_EXPIRY = timedelta(hours=36)
FEEDBACK_MIN_DELAY = timedelta(minutes=30)
MAX_RECENT_SESSIONS = 20
MAX_OPEN_FEEDBACK = 3
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "jackenberater"

JACKET_NONE = "none"
JACKET_LIGHT = "light"
JACKET_WARM = "warm"
JACKET_WINTER = "winter"
JACKET_LEVELS = (JACKET_NONE, JACKET_LIGHT, JACKET_WARM, JACKET_WINTER)
JACKET_RANK = {name: idx for idx, name in enumerate(JACKET_LEVELS)}

RAIN_NONE = "none"
RAIN_TAKE = "take"
RAIN_RECOMMENDED = "recommended"

DISPLAY_HIDDEN = "hidden"
DISPLAY_COMPACT = "compact"
DISPLAY_FULL = "full"

FEEDBACK_TOO_COLD = "too_cold"
FEEDBACK_PERFECT = "perfect"
FEEDBACK_TOO_WARM = "too_warm"
FEEDBACK_NOT_USED = "not_used"
FEEDBACK_VALUES = {
    FEEDBACK_TOO_COLD,
    FEEDBACK_PERFECT,
    FEEDBACK_TOO_WARM,
    FEEDBACK_NOT_USED,
}

PHASE_START = "start"
PHASE_LATER = "later"
PHASE_ALL = "all"
PHASE_VALUES = {PHASE_START, PHASE_LATER, PHASE_ALL}

SIGNAL_PROFILE_CREATED = f"{DOMAIN}_profile_created_{{entry_id}}"
SIGNAL_PROFILE_UPDATED = f"{DOMAIN}_profile_updated_{{entry_id}}"
