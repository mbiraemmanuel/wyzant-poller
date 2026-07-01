import hashlib
import logging
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import Job

logger = logging.getLogger(__name__)

# ── HTML selector config (verified against highered.wyzant.com/tutor/jobs) ──
_JOB_CARD_SEL = "div.academy-card"
_JOB_SUBJECT_SEL = "h3"           # subject name is the job "title"
_JOB_APPLY_LINK_SEL = "a[href*='jobapplication?id=']"
_JOB_DESC_SEL = "p.job-description"
_JOB_STUDENT_SEL = "p.text-semibold"
# ────────────────────────────────────────────────────────────────────────────

# Wyzant redirects www → highered subdomain; follow it automatically.
_JOBS_PARAMS = {"subject_id": "-1", "sort_by": "1"}  # -1 = My subjects (qualified only)

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_LOGIN_INDICATORS = [
    "sign in to continue",
    "please log in",
    "sign in to your account",
    "create an account or sign in",
]


class AuthExpiredError(Exception):
    pass


def fetch_jobs(config: Config, session: requests.Session) -> list[Job]:
    if config.jobs_json_endpoint:
        return _fetch_json(config, session)
    return _fetch_html(config, session)


def _fetch_json(config: Config, session: requests.Session) -> list[Job]:
    resp = session.get(config.jobs_json_endpoint, headers=_REQUEST_HEADERS, timeout=20)
    _check_response(resp)

    data = resp.json()
    jobs_raw = (
        data.get("jobs")
        or data.get("results")
        or data.get("data", {}).get("listings")
        or data.get("listings")
        or []
    )

    jobs: list[Job] = []
    for item in jobs_raw:
        job_id = str(item.get("id") or item.get("jobId") or item.get("job_id") or "")
        if not job_id:
            continue
        title = item.get("title") or item.get("name") or item.get("subject") or "New Job"
        path = item.get("url") or item.get("path") or f"/tutor/jobs/{job_id}"
        url = path if path.startswith("http") else f"https://www.wyzant.com{path}"
        subject = item.get("subject") or item.get("topic")
        jobs.append(Job(id=job_id, title=str(title), url=url, subject=subject))

    if jobs_raw and not jobs:
        logger.warning("JSON response had items but parsing yielded 0 — check JSON field names")

    logger.debug("Fetched %d jobs via JSON", len(jobs))
    return jobs


def _fetch_html(config: Config, session: requests.Session) -> list[Job]:
    resp = session.get(
        config.jobs_url, params=_JOBS_PARAMS, headers=_REQUEST_HEADERS, timeout=20
    )
    _check_response(resp)

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select(_JOB_CARD_SEL)

    if not cards:
        text_lower = resp.text.lower()
        if any(ind in text_lower for ind in _LOGIN_INDICATORS):
            raise AuthExpiredError("Page is showing a login wall — session expired")
        # "Sorry, no jobs" is a valid empty state — not an error
        logger.debug("No job cards on page (board may be empty for current subjects)")
        return []

    jobs: list[Job] = []
    for card in cards:
        # Skip unqualified cards (no apply link available)
        apply_link_el = card.select_one(_JOB_APPLY_LINK_SEL)
        job_id = _id_from_apply_link(apply_link_el)
        if not job_id:
            # Fall back to a stable hash of student+subject so we still track it
            job_id = _card_hash(card)

        subject_el = card.select_one(_JOB_SUBJECT_SEL)
        student_el = card.select_one(_JOB_STUDENT_SEL)
        subject = subject_el.get_text(strip=True) if subject_el else "New Job"
        student = student_el.get_text(strip=True) if student_el else ""
        title = f"{subject} — {student}" if student else subject

        if apply_link_el and apply_link_el.get("href"):
            url = apply_link_el["href"]
            if not url.startswith("http"):
                url = f"https://www.wyzant.com{url}"
        else:
            url = config.jobs_url

        jobs.append(Job(id=job_id, title=title, url=url, subject=subject))

    logger.debug("Fetched %d job cards via HTML", len(jobs))
    return jobs


def _check_response(resp: requests.Response) -> None:
    if resp.status_code in (401, 403):
        raise AuthExpiredError(f"HTTP {resp.status_code} — session likely expired")
    if resp.status_code != 200:
        resp.raise_for_status()
    final_url = str(resp.url)
    if re.search(r"/login(?:/|$|\?)", final_url):
        raise AuthExpiredError(f"Redirected to login page: {final_url}")


def _id_from_apply_link(link_el: Optional[BeautifulSoup]) -> Optional[str]:
    if not link_el:
        return None
    href = link_el.get("href", "")
    qs = parse_qs(urlparse(href).query)
    ids = qs.get("id", [])
    return ids[0].strip() if ids else None


def _card_hash(card: BeautifulSoup) -> str:
    """Stable pseudo-ID when no apply link is present."""
    subject_el = card.select_one(_JOB_SUBJECT_SEL)
    student_el = card.select_one(_JOB_STUDENT_SEL)
    subject = subject_el.get_text(strip=True) if subject_el else ""
    student = student_el.get_text(strip=True) if student_el else ""
    stable = f"{subject}|{student}"
    return "h:" + hashlib.sha1(stable.encode()).hexdigest()[:16]
