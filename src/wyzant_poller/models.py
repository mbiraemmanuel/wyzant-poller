from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Job:
    id: str
    title: str
    url: str
    subject: Optional[str] = None
    posted_at: Optional[datetime] = None
