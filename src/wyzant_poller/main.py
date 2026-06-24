import argparse
import logging
import random
import signal
import sys
import time
from pathlib import Path

import requests

from .auth import AuthManager
from .config import Config, load_config
import smtplib
from email.message import EmailMessage

from bs4 import BeautifulSoup

from .fetch import AuthExpiredError, _JOBS_PARAMS, _REQUEST_HEADERS, _check_response, fetch_jobs
from .notify import EmailNotifier, MultiNotifier, NtfyNotifier, TwilioNotifier
from .store import Store

logger = logging.getLogger(__name__)

_running = True


def _on_sigterm(*_: object) -> None:
    global _running
    logger.info("SIGTERM received — shutting down after current cycle")
    _running = False


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def _make_session(auth: AuthManager) -> requests.Session:
    session = requests.Session()
    session.cookies.update(auth.cookies())
    return session


def _health_check(config: Config, session: requests.Session) -> bool:
    """Fetch all-subjects view. Returns True if healthy, sends alert email and returns False if not."""
    try:
        resp = session.get(
            config.jobs_url,
            params={**_JOBS_PARAMS, "subject_id": "-2"},
            headers=_REQUEST_HEADERS,
            timeout=20,
        )
        _check_response(resp)
        count = len(BeautifulSoup(resp.text, "html.parser").select("div.academy-card"))
        if count > 0:
            logger.info("Health check OK — %d jobs visible on all-subjects board", count)
            return True
        logger.error("Health check FAILED — all-subjects view returned 0 job cards")
    except Exception as exc:
        logger.error("Health check error: %s", exc)

    try:
        msg = EmailMessage()
        msg["Subject"] = "Wyzant Poller — Session May Be Dead"
        msg["From"] = config.email_from or config.smtp_username
        msg["To"] = config.alert_email
        msg.set_content(
            "The Wyzant job poller health check failed.\n\n"
            "The 'all subjects' board returned 0 jobs, which should never happen.\n"
            "This usually means the session has expired or Wyzant blocked the request.\n\n"
            "Check the log and restart the poller:\n"
            f"  tail -50 {config.state_dir}/poller.log\n\n"
            "— Wyzant Job Poller"
        )
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(msg)
        logger.info("Health alert sent → %s", config.alert_email)
    except Exception:
        logger.exception("Failed to send health alert")

    return False


def _poll_once(
    config: Config,
    auth: AuthManager,
    store: Store,
    notifier: NtfyNotifier,
    dry_run: bool,
) -> None:
    session = _make_session(auth)
    try:
        jobs = fetch_jobs(config, session)
    except AuthExpiredError as exc:
        logger.warning("%s — triggering Playwright re-login", exc)
        auth.login()
        session = _make_session(auth)
        jobs = fetch_jobs(config, session)

    if not store.is_baseline_established():
        store.establish_baseline(jobs)
        return

    if not jobs:
        logger.debug("My-subjects board returned 0 jobs (none matching Christine's subjects)")
        return

    new = store.new_jobs(jobs)
    logger.info("Poll complete: %d total, %d new", len(jobs), len(new))

    if not new:
        return

    if dry_run:
        for job in new:
            logger.info("[DRY RUN] Would notify: [%s] %s → %s", job.id, job.title, job.url)
        return

    for job in new:
        try:
            notifier.send(job)
        except Exception:
            logger.exception("Notification failed for job %s (%s)", job.id, job.title)

    # Only persist after notifications so a mid-cycle crash doesn't silently drop a job.
    store.mark_seen(new)


def _cmd_run(args: argparse.Namespace, config: Config) -> None:
    _setup_logging(config.log_level)
    logger.info("Starting Wyzant poller — %s", config)

    auth = AuthManager(config)
    store = Store(config.state_dir / "jobs.db")

    notifiers: list = [NtfyNotifier(config.ntfy_server, config.ntfy_topic)]
    if config.email_to and config.smtp_username and config.smtp_password:
        notifiers.append(
            EmailNotifier(
                smtp_host=config.smtp_host,
                smtp_port=config.smtp_port,
                username=config.smtp_username,
                password=config.smtp_password,
                from_addr=config.email_from or config.smtp_username,
                to_addrs=config.email_to,
            )
        )
        logger.info("Email/SMS notifications enabled → %s", ", ".join(config.email_to))
    if config.sms_to and config.twilio_account_sid and config.twilio_auth_token and config.twilio_from:
        notifiers.append(
            TwilioNotifier(
                account_sid=config.twilio_account_sid,
                auth_token=config.twilio_auth_token,
                from_number=config.twilio_from,
                to_numbers=config.sms_to,
            )
        )
        logger.info("SMS notifications enabled → %s", ", ".join(config.sms_to))
    notifier = MultiNotifier(notifiers)

    signal.signal(signal.SIGTERM, _on_sigterm)

    if not config.wyzant_cookie and not auth.has_saved_session():
        auth.login()

    backoff = 0.0
    MAX_BACKOFF = 600.0
    health_alert_sent = False  # avoid flooding on repeated failures

    try:
        while _running:
            try:
                session = _make_session(auth)

                # Health check: all-subjects view should always have jobs
                if config.alert_email and config.smtp_username and config.smtp_password:
                    healthy = _health_check(config, session)
                    if not healthy and not health_alert_sent:
                        health_alert_sent = True
                    elif healthy and health_alert_sent:
                        health_alert_sent = False
                        logger.info("Health check recovered")

                _poll_once(config, auth, store, notifier, dry_run=args.dry_run)
                backoff = 0.0
            except AuthExpiredError:
                logger.error("Auth expired and re-login failed — check credentials/selectors")
                backoff = min((backoff or 60.0) * 2, MAX_BACKOFF)
            except requests.exceptions.Timeout:
                # Stale connection after Mac wake — retry once immediately, no backoff
                logger.warning("Request timed out (likely stale connection after sleep) — retrying once")
                try:
                    session = _make_session(auth)
                    _poll_once(config, auth, store, notifier, dry_run=args.dry_run)
                    backoff = 0.0
                except Exception:
                    logger.exception("Retry also failed")
                    backoff = min((backoff or 30.0) * 2, MAX_BACKOFF)
            except Exception:
                logger.exception("Unexpected error during poll")
                backoff = min((backoff or 30.0) * 2, MAX_BACKOFF)

            if not _running:
                break

            wait = backoff if backoff else random.uniform(config.poll_min, config.poll_max)
            logger.debug("Next poll in %.0fs", wait)

            deadline = time.monotonic() + wait
            while _running and time.monotonic() < deadline:
                time.sleep(min(5.0, deadline - time.monotonic()))

    except KeyboardInterrupt:
        logger.info("Interrupted — stopping")
    finally:
        store.close()

    logger.info("Poller stopped")


def _cmd_inspect(args: argparse.Namespace, config: Config) -> None:
    _setup_logging("DEBUG")
    auth = AuthManager(config)
    if not config.wyzant_cookie and not auth.has_saved_session():
        auth.login()

    session = _make_session(auth)
    url = config.jobs_json_endpoint or config.jobs_url
    is_json = bool(config.jobs_json_endpoint)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    if is_json:
        headers["Accept"] = "application/json"

    resp = session.get(url, headers=headers, timeout=20)
    ext = "json" if is_json else "html"
    out = Path(f"inspect_output.{ext}")
    out.write_text(resp.text, encoding="utf-8")
    logger.info("HTTP %d | final URL: %s", resp.status_code, resp.url)
    logger.info("Saved %d bytes → %s", len(resp.text), out.resolve())


def main() -> None:
    parser = argparse.ArgumentParser(prog="wyzant-poller", description="Wyzant job alert daemon")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and log without sending notifications")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "inspect"],
        help="run: start polling loop (default) | inspect: dump the jobs page to a file",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.command == "inspect":
        _cmd_inspect(args, config)
    else:
        _cmd_run(args, config)


if __name__ == "__main__":
    main()
