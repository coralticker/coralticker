"""HTTP fetch wrapper. Implements arch §2.4 retry policy + §2.5 polite-scraper
hygiene. Returns explicit status objects rather than raising — the orchestrator
in run.py decides what failure shape to write to scraper_runs.error_class.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


# Decision #13 — standard Chrome on Windows UA, NOT a CoralTicker-branded UA.
# Forker-abuse blanket-bans land on custom UAs first; standard browser UA
# blends with normal traffic. Updated when Chrome stable bumps majors.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Per arch §2.4 retry policy. No external library — plain loop per decision #12.
RETRY_BACKOFF_429_5XX = (30, 60, 120)  # seconds; per-attempt backoff
NETWORK_RETRY_DELAY = 10  # seconds; flat per-retry sleep on network error path
REQUEST_TIMEOUT = 30  # per-request hard ceiling; well under workflow 10-min cap


# Block-detection signatures. Cloudflare interstitial bodies + WAF challenge
# pages return 2xx but contain these markers. Per arch §2.4 block row: NO
# retry on block; rotate UA + flip vendors.active=false is the response.
BLOCK_SIGNATURES = (
    b"Just a moment...",            # Cloudflare challenge page
    b"cf-challenge",
    b"Attention Required! | Cloudflare",
    b"Access denied | Cloudflare",
    b"<title>Access denied</title>",
)


@dataclass
class FetchResult:
    """Explicit fetch outcome. Orchestrator branches on .error_class."""
    body: bytes | None
    status_code: int | None
    error_class: str | None  # one of arch §2.4: http_429 / http_5xx / network / block / other / None on success
    error_message: str | None


def fetch(url: str, request_delay_sec: float = 2.0) -> FetchResult:
    """GET url with retry per arch §2.4. Sleeps request_delay_sec BEFORE the
    request (caller controls cadence; we control hygiene)."""
    time.sleep(request_delay_sec)

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"}

    last_status = None
    last_message = None

    for attempt, backoff in enumerate(RETRY_BACKOFF_429_5XX, start=1):
        try:
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_message = f"{type(e).__name__}: {e}"
            log.warning("fetch %s attempt %d network error: %s", url, attempt, last_message)
            if attempt < len(RETRY_BACKOFF_429_5XX):
                time.sleep(NETWORK_RETRY_DELAY)
                continue
            return FetchResult(None, None, "network", last_message)

        last_status = r.status_code

        if r.status_code == 200:
            if _looks_blocked(r.content):
                return FetchResult(None, 200, "block", "200 with cloudflare/WAF body signature")
            return FetchResult(r.content, 200, None, None)

        if r.status_code == 429:
            log.warning("fetch %s attempt %d HTTP 429; backoff %ds", url, attempt, backoff)
            time.sleep(backoff)
            continue

        if 500 <= r.status_code < 600:
            log.warning("fetch %s attempt %d HTTP %d; backoff %ds", url, attempt, r.status_code, backoff)
            time.sleep(backoff)
            continue

        if r.status_code == 403:
            # 403 with WAF body markers = block; without = treat as 5xx-shaped
            # failure. 503 falls into the 5xx-range branch above; only 403
            # reaches here.
            if _looks_blocked(r.content):
                return FetchResult(None, 403, "block", "HTTP 403 with WAF body")
            time.sleep(backoff)
            continue

        # 4xx other than 429/403 — don't retry, surface as other
        return FetchResult(None, r.status_code, "other", f"HTTP {r.status_code}")

    # Loop exhausted
    if last_status == 429:
        return FetchResult(None, 429, "http_429", "3 attempts exhausted")
    if last_status and 500 <= last_status < 600:
        return FetchResult(None, last_status, "http_5xx", f"3 attempts exhausted at HTTP {last_status}")
    return FetchResult(None, last_status, "other", last_message or "unknown failure")


def fetch_image(url: str) -> bytes | None:
    """Single-attempt image fetch per CTK-019 #55 — does NOT inherit decision
    #12's 3x retry. Image is presentation; permanent failure returns None and
    the caller writes image_url=null + continues."""
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    except (requests.ConnectionError, requests.Timeout) as e:
        log.info("image fetch %s failed (network): %s", url, e)
        return None
    if r.status_code != 200:
        log.info("image fetch %s failed: HTTP %d", url, r.status_code)
        return None
    return r.content


def _looks_blocked(body: bytes | None) -> bool:
    if not body:
        return False
    snippet = body[:4096]
    return any(sig in snippet for sig in BLOCK_SIGNATURES)
