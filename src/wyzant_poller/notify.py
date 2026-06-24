import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

import requests

from .models import Job

logger = logging.getLogger(__name__)


class Notifier(ABC):
    @abstractmethod
    def send(self, job: Job) -> None: ...


class NtfyNotifier(Notifier):
    def __init__(self, server: str, topic: str) -> None:
        self._url = f"{server.rstrip('/')}/{topic}"

    def send(self, job: Job) -> None:
        subject_tag = job.subject.lower().replace(" ", "_") if job.subject else "tutoring"
        resp = requests.post(
            self._url,
            data=job.title.encode("utf-8"),
            headers={
                "Title": "New Wyzant Job",
                "Click": job.url,
                "Priority": "high",
                "Tags": f"school,{subject_tag}",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("ntfy sent: [%s] %s", job.id, job.title)


class EmailNotifier(Notifier):
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: list,
    ) -> None:
        self._host = smtp_host
        self._port = smtp_port
        self._username = username
        self._password = password
        self._from = from_addr
        self._to = to_addrs

    def send(self, job: Job) -> None:
        body = (
            f"A new tutoring job was just posted on Wyzant:\n\n"
            f"Subject: {job.subject or 'N/A'}\n"
            f"Title:   {job.title}\n\n"
            f"Apply here:\n{job.url}\n\n"
            f"— Wyzant Job Poller"
        )
        with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(self._username, self._password)
            for addr in self._to:
                msg = EmailMessage()
                msg["Subject"] = f"New Wyzant Job: {job.title}"
                msg["From"] = self._from
                msg["To"] = addr
                msg.set_content(body)
                smtp.send_message(msg)
                logger.info("email sent: [%s] %s → %s", job.id, job.title, addr)


class MultiNotifier(Notifier):
    """Fan-out to multiple notifiers; logs but continues on individual failures."""

    def __init__(self, notifiers: list) -> None:
        self._notifiers = notifiers

    def send(self, job: Job) -> None:
        for notifier in self._notifiers:
            try:
                notifier.send(job)
            except Exception:
                logger.exception("%s failed for job %s", type(notifier).__name__, job.id)


class TwilioNotifier(Notifier):
    def __init__(self, account_sid: str, auth_token: str, from_number: str, to_numbers: list) -> None:
        from twilio.rest import Client
        self._client = Client(account_sid, auth_token)
        self._from = from_number
        self._to = to_numbers

    def send(self, job: Job) -> None:
        body = f"New Wyzant job: {job.title}\n{job.url}"
        for number in self._to:
            self._client.messages.create(body=body, from_=self._from, to=number)
            logger.info("SMS sent: [%s] %s → %s", job.id, job.title, number)
