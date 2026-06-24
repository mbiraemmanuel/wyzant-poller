# Phase 3 stub — subject filtering and per-topic routing go here.
# Currently all jobs pass through.

from typing import Optional

from .models import Job


def should_notify(job: Job, allowlist: Optional[list[str]]) -> bool:
    if not allowlist:
        return True
    text = f"{job.title} {job.subject or ''}".lower()
    return any(kw.lower() in text for kw in allowlist)
