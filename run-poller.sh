#!/bin/bash
# Use env -i to avoid shell env vars clashing with XPC_SERVICE_NAME (causes SIGABRT on Apple Python)
exec env -i \
    HOME="/Users/kaizen" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    PYTHONUNBUFFERED="1" \
    TZ="America/New_York" \
    /Users/kaizen/Documents/Wyzant/wyzant-poller/.venv/bin/python -m wyzant_poller
