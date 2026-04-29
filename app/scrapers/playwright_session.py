"""Persistent Playwright profiles, one per job site.

Each site gets its own user-data directory under
`settings.playwright_profiles_dir / profile-<site>`. The first time you run
`scripts/login_once.py <site>`, Playwright opens a real window and you sign
in yourself. Cookies/localStorage persist in that directory; subsequent
scraper runs reuse the profile so credentials never need to live in code.

This module offers two helpers:
    - `sync_context(site, headless=True)` : context-manager yielding
      (playwright, context) for use inside scrapers.
    - `launch_for_login(site)` : convenience used by `scripts/login_once.py`
      to open a visible window and block on human input.

We use the sync Playwright API because the rest of this codebase is
synchronous and FastAPI endpoints that trigger Playwright run it out-of-band
(the caller shouldn't wait on an apply flow anyway).
"""

from __future__ import annotations

import logging
import os
import random
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.config import settings

logger = logging.getLogger(__name__)


# Reasonable default viewport for job boards. Avoid anything too tall so the
# non-headless window isn't overwhelming on 1080p displays.
DEFAULT_VIEWPORT = {"width": 1400, "height": 900}

# A list of valid site ids. Kept small on purpose; adding one requires also
# adding a scraper module under app/scrapers/.
SUPPORTED_SITES = {"linkedin", "wttj", "jobright"}


def profile_dir(site: str) -> Path:
    """Return (and ensure) the persistent user-data dir for `site`.

    Honors per-site overrides from the environment (`WTTJ_PROFILE_DIR`,
    etc.) which let the user point at an existing browser profile (e.g.
    their real Chrome user-data directory) when Playwright-driven Chromium
    login isn't viable for that site.
    """
    if site not in SUPPORTED_SITES:
        raise ValueError(
            f"unsupported site '{site}'. Expected one of {sorted(SUPPORTED_SITES)}."
        )
    override = settings.site_profile_override(site)
    if override:
        # Trust the override path as-is; don't create parents (the user
        # pointed us at their own browser's user-data dir, which must
        # already exist). But do resolve `%VAR%` / ~ for ergonomics.
        return Path(os.path.expandvars(os.path.expanduser(override)))
    base = settings.playwright_profiles_path / f"profile-{site}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def human_sleep(prefs) -> None:
    """Throttle between page loads with a random delay inside the prefs
    window. Called by scrapers after every navigation."""
    throttle = getattr(prefs, "scraper", None)
    if throttle is None:
        return
    lo = max(0, int(getattr(throttle, "min_delay_ms", 1500))) / 1000.0
    hi = max(lo, int(getattr(throttle, "max_delay_ms", 4000))) / 1000.0
    delay = random.uniform(lo, hi)
    time.sleep(delay)


# A realistic desktop UA string. Playwright's default UA includes "HeadlessChrome"
# in some builds which trips trivial bot filters; overriding it is cheap insurance.
_STEALTH_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Flags that reduce the "this is automation" fingerprint surface. Sites like
# WTTJ disable submit buttons until their JS decides the browser is real,
# and the default `navigator.webdriver = true` plus automation-specific
# command line switches are the easiest signals for them to key off.
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-default-browser-check",
    "--no-first-run",
]


# Small JS shim injected on every new page. Masks the two most common
# automation tells without breaking anything. Kept intentionally minimal.
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""


def _using_external_profile(site: str) -> bool:
    """True when this site points at an external browser user-data-dir
    (`settings.site_profile_override`). Used to back off on UA spoofing /
    automation flags, since those will fight the real browser's own
    behavior and sometimes invalidate the session cookie."""
    return bool(settings.site_profile_override(site))


@contextmanager
def sync_context(
    site: str,
    *,
    headless: bool = True,
    viewport: Optional[dict] = None,
    prefer_real_chrome: bool = True,
) -> Iterator[tuple]:
    """Context manager that yields `(playwright, persistent_context)` for
    `site`. Closes everything on exit.

    When `prefer_real_chrome=True` (the default), behavior depends on
    :envvar:`PLAYWRIGHT_CHANNEL` and profile overrides:
    - External profile (`LINKEDIN_PROFILE_DIR`, etc.): launches that browser
      via Playwright's channel API. Default channel is ``chrome``; set
      ``PLAYWRIGHT_CHANNEL=msedge`` to use installed Microsoft Edge with an
      Edge user-data directory.
    - Default ``.playwright/profile-*`` dirs use bundled Chromium unless
      ``PLAYWRIGHT_CHANNEL`` is set (e.g. ``msedge`` to drive Edge for those
      profiles too, when supported on your OS).

    Scraper modules import Playwright lazily via this function so the rest
    of the app (tests, CI, local dev without Playwright installed) keeps
    working even when the browser binaries aren't present.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "Playwright is not installed. Run `pip install playwright` and "
            "`playwright install chromium`."
        ) from exc

    pw = sync_playwright().start()
    try:
        using_external = _using_external_profile(site)
        launch_kwargs = dict(
            user_data_dir=str(profile_dir(site)),
            headless=headless,
            viewport=viewport or DEFAULT_VIEWPORT,
            args=list(_STEALTH_ARGS),
            ignore_default_args=["--enable-automation"],
        )
        # When reusing an external browser profile (Chrome or Edge user-data
        # dir), let the native UA through. Pin "Default" so the browser does
        # not pop a profile picker (which can block navigation headless).
        if using_external:
            launch_kwargs["args"] = list(launch_kwargs["args"]) + [
                "--profile-directory=Default",
            ]
        else:
            launch_kwargs["user_agent"] = _STEALTH_UA

        resolved_channel: Optional[str] = None
        if using_external:
            resolved_channel = settings.playwright_channel or "chrome"
        elif settings.playwright_channel:
            resolved_channel = settings.playwright_channel

        try:
            if resolved_channel:
                context = pw.chromium.launch_persistent_context(
                    channel=resolved_channel,
                    **launch_kwargs,
                )
            else:
                context = pw.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as exc:
            if using_external:
                raise RuntimeError(
                    f"Site '{site}' is configured with an external profile "
                    f"override but the browser could not be launched "
                    f"(channel={resolved_channel!r}): {exc}. Install Google "
                    "Chrome or Microsoft Edge, set PLAYWRIGHT_CHANNEL to "
                    "`chrome` or `msedge` to match your user-data directory, "
                    f"or clear {site.upper()}_PROFILE_DIR to use the default "
                    "`.playwright/` profile (bundled Chromium)."
                ) from exc
            raise

        try:
            try:
                context.add_init_script(_STEALTH_INIT_SCRIPT)
            except Exception:  # pragma: no cover
                logger.exception("failed to install stealth init script for %s", site)
            yield pw, context
        finally:
            try:
                context.close()
            except Exception:  # pragma: no cover
                logger.exception("failed to close playwright context for %s", site)
    finally:
        try:
            pw.stop()
        except Exception:  # pragma: no cover
            logger.exception("failed to stop playwright for %s", site)


LOGIN_URLS: dict[str, str] = {
    "linkedin": "https://www.linkedin.com/login",
    "wttj": "https://www.welcometothejungle.com/en/signin",
    "jobright": "https://jobright.ai/sign-in",
}


# Per-site selectors for the email + password inputs on the sign-in page.
# Each list is tried in order; the first selector that matches a visible
# element gets filled. Missing an element is never fatal - we just skip the
# auto-fill and let the human type it.
_LOGIN_FIELD_SELECTORS: dict[str, dict[str, list[str]]] = {
    "linkedin": {
        "email":    ["input#username", "input[name='session_key']", "input[type='email']"],
        "password": ["input#password", "input[name='session_password']", "input[type='password']"],
    },
    "wttj": {
        "email":    ["input[name='email']", "input[type='email']"],
        "password": ["input[name='password']", "input[type='password']"],
    },
    "jobright": {
        "email":    ["input[name='email']", "input[type='email']"],
        "password": ["input[name='password']", "input[type='password']"],
    },
}


def _try_fill(page, selectors: list[str], value: str) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.fill(value, timeout=2000)
            return True
        except Exception:
            continue
    return False


# Selectors for cookie / consent banners we try to auto-dismiss before the
# human starts interacting. Listed in preference order; first visible match
# gets clicked. Failures are silent - the user can still click manually.
_CONSENT_SELECTORS: dict[str, list[str]] = {
    "wttj": [
        "#didomi-notice-agree-button",
        "button#didomi-notice-agree-button",
        "button[aria-label='Agree and close']",
        "button:has-text('Accept')",
        "button:has-text('Agree and close')",
        "button:has-text('I agree')",
    ],
    "linkedin": [
        "button[action-type='ACCEPT']",
        "button:has-text('Accept')",
    ],
    "jobright": [
        "button:has-text('Accept')",
        "button:has-text('Got it')",
    ],
}


def _dismiss_consent_banner(page, site: str) -> bool:
    """Best-effort click of a cookie/consent accept button. Returns True
    if we clicked something, False otherwise. Never raises."""
    selectors = _CONSENT_SELECTORS.get(site, [])
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            # The WTTJ banner renders in a fixed iframe that takes a moment
            # to hydrate; wait_for a short beat so we don't miss it.
            loc.wait_for(state="visible", timeout=2500)
            loc.click(timeout=1500)
            return True
        except Exception:
            continue
    # Last-ditch: remove common banner containers from the DOM so they can
    # never block clicks even if the accept button itself isn't reachable.
    try:
        page.evaluate(
            """
            const sels = ['#didomi-host', '#didomi-notice', '.didomi-popup-container',
                          '[id^=\"didomi\"]'];
            for (const s of sels) {
              document.querySelectorAll(s).forEach(el => el.remove());
            }
            document.body && (document.body.style.overflow = 'auto');
            """
        )
    except Exception:
        pass
    return False


def launch_for_login(site: str, *, email: str = "", password: str = "") -> None:
    """Open a visible window on the site's sign-in page and block until the
    user presses Enter in the terminal.

    If `email` / `password` are provided, we pre-fill those fields so you
    only have to click the Sign-in button (plus any 2FA / captcha). SSO-only
    accounts should call with empty credentials and use --sso from login_once.
    Leave them blank to type everything manually. Session cookies are
    persisted under the configured profile dir for later headless runs.
    """
    if site not in LOGIN_URLS:
        raise ValueError(f"no login URL registered for site '{site}'")
    with sync_context(site, headless=False) as (_, context):
        page = context.new_page()
        page.goto(LOGIN_URLS[site])

        # Give cookie banners a moment to render, then try to dismiss them
        # so the sign-in button is actually clickable. Silent on failure.
        page.wait_for_timeout(1500)
        _dismiss_consent_banner(page, site)

        if email or password:
            page.wait_for_timeout(800)  # let the form render before we fill
            sels = _LOGIN_FIELD_SELECTORS.get(site, {})
            if email:
                _try_fill(page, sels.get("email", []), email)
            if password:
                _try_fill(page, sels.get("password", []), password)
            print(
                f"\n[{site}] Credentials pre-filled from .env.\n"
                "Click 'Sign in' yourself, handle any 2FA / captcha, land on "
                "your home feed, then press Enter here to save cookies."
            )
        else:
            print(
                f"\n[{site}] A browser window is open. Sign in normally.\n"
                "When you're fully logged in (you can see your job feed/home page), "
                "press Enter here to save cookies and close the window."
            )
        try:
            input()
        except EOFError:  # pragma: no cover - interactive tool
            pass


# Post-login "home" pages used to probe whether a persistent profile is
# still authenticated. Each of these redirects to the site's sign-in page
# when you're logged out, so we can detect auth state purely by looking at
# the final URL.
_AUTH_PROBE_URLS: dict[str, str] = {
    "linkedin": "https://www.linkedin.com/feed/",
    "wttj":     "https://www.welcometothejungle.com/en/me",
    "jobright": "https://jobright.ai/jobs/recommend",
}

# URL substrings that mean "we got bounced to a sign-in page" regardless
# of site.
_LOGGED_OUT_MARKERS = (
    "login", "signin", "sign-in", "sign_in", "/auth", "authwall", "checkpoint",
)


def check_login(site: str, *, timeout_ms: int = 20000, headless: bool = True) -> dict:
    """Open the site's "home" URL in a headless Playwright context and
    report whether the persistent profile is still authenticated.

    Returns a dict shaped like:
        {
          "site": "linkedin",
          "logged_in": True,
          "final_url": "https://www.linkedin.com/feed/",
          "started_url": "https://www.linkedin.com/feed/",
          "notes": "stayed on authenticated page",
          "error": None,
        }
    """
    if site not in _AUTH_PROBE_URLS:
        raise ValueError(f"unknown site '{site}'")

    result: dict = {
        "site": site,
        "logged_in": False,
        "started_url": _AUTH_PROBE_URLS[site],
        "final_url": None,
        "notes": "",
        "error": None,
    }
    try:
        with sync_context(site, headless=headless) as (_, context):
            page = context.new_page()
            page.goto(_AUTH_PROBE_URLS[site], wait_until="domcontentloaded", timeout=timeout_ms)
            # Some sites do client-side redirects; give the JS a beat.
            page.wait_for_timeout(1500)
            final_url = (page.url or "").lower()
            result["final_url"] = page.url

            looks_logged_out = any(m in final_url for m in _LOGGED_OUT_MARKERS)
            # If the site bounced us to a different path than the one we asked
            # for (e.g. /jobs/recommend -> /), that's usually an auth redirect
            # even when the destination URL doesn't contain "login".
            from urllib.parse import urlparse
            started_path = urlparse(_AUTH_PROBE_URLS[site]).path.rstrip("/")
            final_path = urlparse(page.url or "").path.rstrip("/")
            bounced_elsewhere = (
                bool(started_path)
                and final_path != started_path
                and started_path not in final_path
            )

            if looks_logged_out or bounced_elsewhere:
                result["notes"] = (
                    "redirected to a sign-in / auth page" if looks_logged_out
                    else f"bounced from {started_path or '/'} to {final_path or '/'}; probably logged out"
                )
                result["logged_in"] = False
            else:
                # Positive signal: on LinkedIn the feed has `#global-nav`;
                # on WTTJ, the me page has a profile header; on Jobright,
                # the recommend page renders job cards. We probe cheaply.
                positive_selectors = {
                    "linkedin": ["nav.global-nav", "#global-nav", "a[href*='/in/']"],
                    "wttj":     ["a[href*='/en/logout']", "[data-testid='user-menu']"],
                    "jobright": ["[data-testid='job-card']", "a[href*='/jobs/']"],
                }.get(site, [])
                saw_positive = False
                for sel in positive_selectors:
                    try:
                        if page.locator(sel).first.count() > 0:
                            saw_positive = True
                            break
                    except Exception:
                        continue
                if saw_positive:
                    result["logged_in"] = True
                    result["notes"] = "authenticated: found logged-in UI element"
                else:
                    # Inconclusive: URL didn't look like login, but we
                    # couldn't confirm a logged-in element either.
                    result["logged_in"] = True
                    result["notes"] = (
                        "no sign-in redirect; logged-in UI element not matched "
                        "(site may have changed its markup)"
                    )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["notes"] = "playwright call failed"
    return result


__all__ = [
    "DEFAULT_VIEWPORT",
    "SUPPORTED_SITES",
    "LOGIN_URLS",
    "profile_dir",
    "human_sleep",
    "sync_context",
    "launch_for_login",
    "check_login",
]
