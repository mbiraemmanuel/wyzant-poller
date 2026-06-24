import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    wyzant_cookie: Optional[str]
    wyzant_email: Optional[str]
    wyzant_password: Optional[str]
    jobs_url: str
    jobs_json_endpoint: Optional[str]
    ntfy_server: str
    ntfy_topic: str
    # SMS (Twilio)
    twilio_account_sid: Optional[str]
    twilio_auth_token: Optional[str]
    twilio_from: Optional[str]
    sms_to: list
    # Email
    smtp_host: str
    smtp_port: int
    smtp_username: Optional[str]
    smtp_password: Optional[str]
    email_from: Optional[str]
    email_to: list
    alert_email: Optional[str]
    # Polling
    poll_min: int
    poll_max: int
    log_level: str
    state_dir: Path
    tz: str

    def __repr__(self) -> str:
        notifiers = ["ntfy"]
        if self.email_to:
            notifiers.append(f"email→{self.email_to}")
        return (
            f"Config(jobs_url={self.jobs_url!r}, notifiers={notifiers}, "
            f"poll={self.poll_min}-{self.poll_max}s, state_dir={self.state_dir})"
        )


def load_config() -> Config:
    load_dotenv()

    poll_min = int(os.getenv("POLL_MIN", "60"))
    poll_max = int(os.getenv("POLL_MAX", "75"))
    if poll_min < 10:
        raise ValueError(f"POLL_MIN must be ≥10s (got {poll_min})")
    if poll_min >= poll_max:
        raise ValueError(f"POLL_MIN ({poll_min}) must be < POLL_MAX ({poll_max})")

    ntfy_topic = os.getenv("NTFY_TOPIC", "")
    if not ntfy_topic:
        raise ValueError("NTFY_TOPIC is required")

    cookie = os.getenv("WYZANT_COOKIE")
    email = os.getenv("WYZANT_EMAIL")
    password = os.getenv("WYZANT_PASSWORD")
    if not cookie and not (email and password):
        raise ValueError(
            "Set WYZANT_COOKIE (cookie auth) or both WYZANT_EMAIL + WYZANT_PASSWORD (Playwright)"
        )

    sms_to_raw = os.getenv("SMS_TO", "")
    sms_to = [n.strip() for n in sms_to_raw.split(",") if n.strip()] if sms_to_raw else []

    return Config(
        wyzant_cookie=cookie,
        wyzant_email=email,
        wyzant_password=password,
        jobs_url=os.getenv("JOBS_URL", "https://www.wyzant.com/tutor/jobs"),
        jobs_json_endpoint=os.getenv("JOBS_JSON_ENDPOINT") or None,
        ntfy_server=os.getenv("NTFY_SERVER", "https://ntfy.sh"),
        ntfy_topic=ntfy_topic,
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID") or None,
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN") or None,
        twilio_from=os.getenv("TWILIO_FROM") or None,
        sms_to=sms_to,
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        email_from=os.getenv("EMAIL_FROM") or None,
        email_to=[a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()],
        alert_email=os.getenv("ALERT_EMAIL") or None,
        poll_min=poll_min,
        poll_max=poll_max,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        state_dir=Path(os.getenv("STATE_DIR", "/data")),
        tz=os.getenv("TZ", "America/New_York"),
    )
