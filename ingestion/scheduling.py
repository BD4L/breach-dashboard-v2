"""One source plan for manual runs, scheduled collection and external triggers."""
from .additional_sources import FEEDS
from .models import ACTIVE_SOURCE_IDS

PRIORITY = ('ransomlook', 'breachsense', 'hibp', 'vermont', 'sec', 'california', 'new_hampshire')
RECENT_SOURCE_IDS = (*PRIORITY, *FEEDS)
RECENT_CRON = '2,32 * * * *'


def plan_sources(requested: str, *, event: str = '', schedule: str = '') -> list[str]:
    if requested not in {'all', 'recent', *ACTIVE_SOURCE_IDS}:
        raise ValueError('Unknown or reference-only source ID')
    if requested == 'recent' or (event == 'schedule' and schedule == RECENT_CRON):
        return list(dict.fromkeys(RECENT_SOURCE_IDS))
    if requested == 'all':
        return [*PRIORITY, *(s for s in ACTIVE_SOURCE_IDS if s not in PRIORITY)]
    return [requested]
