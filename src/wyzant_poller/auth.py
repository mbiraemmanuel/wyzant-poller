import json
import logging
from pathlib import Path

from .config import Config

logger = logging.getLogger(__name__)


class AuthManager:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._state_path = config.state_dir / "playwright_state.json"

    def cookies(self) -> dict[str, str]:
        """Return cookies suitable for a requests.Session."""
        if self._config.wyzant_cookie:
            return _parse_cookie_header(self._config.wyzant_cookie)
        return self._cookies_from_state()

    def has_saved_session(self) -> bool:
        return self._state_path.exists()

    def login(self) -> None:
        """Log in with Playwright, persist storage state to disk."""
        if not self._config.wyzant_email or not self._config.wyzant_password:
            raise RuntimeError(
                "WYZANT_EMAIL and WYZANT_PASSWORD are required for Playwright login"
            )

        logger.info("Launching Playwright to log in to Wyzant...")
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            try:
                page.goto("https://www.wyzant.com/login", timeout=30_000, wait_until="load")

                # Dismiss cookie consent / overlay if present
                for dismiss_sel in [
                    "#onetrust-accept-btn-handler",
                    "button[id*='accept']",
                    "button[class*='cookie']",
                    "button.close",
                ]:
                    try:
                        btn = page.locator(dismiss_sel)
                        if btn.is_visible(timeout=1_000):
                            btn.click()
                            page.wait_for_timeout(500)
                    except Exception:
                        pass

                # Wyzant renders two copies of the login form in the DOM (one hidden).
                # We use JS to set values directly, which bypasses visibility checks
                # while still triggering React/framework change events.
                page.evaluate(
                    """([u, p]) => {
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        const inputs = document.querySelectorAll('#Username');
                        const passwords = document.querySelectorAll('#Password');
                        // Fill whichever instance is actually visible
                        [inputs[inputs.length - 1]].forEach(el => {
                            setter.call(el, u);
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        });
                        [passwords[passwords.length - 1]].forEach(el => {
                            setter.call(el, p);
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        });
                    }""",
                    [self._config.wyzant_email, self._config.wyzant_password],
                )
                # Submit by pressing Enter on the password field (more human-like than button click)
                page.locator("button[type='submit']", has_text="Log in").click()
                page.wait_for_timeout(1000)

                # Wait up to 15s for the URL to move off the login page
                try:
                    page.wait_for_url(
                        lambda url: "/login" not in url,
                        timeout=15_000,
                    )
                except PWTimeout:
                    # Collect any visible error message before raising
                    error_msg = ""
                    for err_sel in [".alert", ".error", ".validation-summary-errors", "[class*='error']"]:
                        try:
                            error_msg = page.locator(err_sel).first.inner_text(timeout=500)
                            break
                        except Exception:
                            pass
                    post_path = str(self._state_path.parent / "login_post_debug.png")
                    page.screenshot(path=post_path)
                    logger.error("Post-submit URL: %s | Error text: %r", page.url, error_msg)
                    raise RuntimeError(
                        f"Login did not navigate away from /login. "
                        f"Error: {error_msg or 'none visible'}. Screenshot: {post_path}"
                    )
                self._state_path.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(self._state_path))
                logger.info("Login successful, session saved to %s", self._state_path)
            except PWTimeout as exc:
                raise RuntimeError(f"Playwright login timed out: {exc}") from exc
            finally:
                browser.close()

    def _cookies_from_state(self) -> dict[str, str]:
        if not self._state_path.exists():
            return {}
        try:
            state = json.loads(self._state_path.read_text())
            return {
                c["name"]: c["value"]
                for c in state.get("cookies", [])
                if "wyzant.com" in c.get("domain", "")
            }
        except (json.JSONDecodeError, KeyError):
            logger.warning("Couldn't parse saved Playwright state; will re-login")
            return {}


def _parse_cookie_header(header: str) -> dict[str, str]:
    """Parse 'name=val; name2=val2' into a plain dict."""
    result: dict[str, str] = {}
    for part in header.split(";"):
        if "=" in part:
            name, _, val = part.strip().partition("=")
            result[name.strip()] = val.strip()
    return result
