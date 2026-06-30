"""scripts/email_digest_watchdog.py — CTK-218 no-send heartbeat for the daily email
digest.

WHY this exists: the email digest now rides the discord-digest.yml dispatch (CTK-218),
but a trigger that shares a workflow can still silently not-send if RESEND_API_KEY goes
missing off-prod (the digest takes its keyless dry-run path and returns success without
sending) or the dispatch never fires at all. This watchdog is a SEPARATE GH-scheduled
workflow (email-digest-watchdog.yml) so it does NOT share the digest's failure mode — a
different language, a different DB driver, an independent trigger. If the digest path is
wholly broken, this still runs and pings.

WHAT it checks: a successful send writes one email_digest_runs row per UTC date (sent_count
>= 1). At 18:00 UTC — five hours after the 13:00 UTC digest fire — today's UTC-date row
should exist. Absent row -> ping the operator channel.

SELF-DISAMBIGUATION: the row is sent-only, so a legit zero-send day (no confirmed
recipients, or zero qualifying drops in the 24h window) ALSO has no row. Rather than
suppress those (which would re-open the silent-gap this ticket closes), the alert reports
the day's qualifying-drops count AND branches the copy on it (leading color dot) so the
operator can tell the two apart at a glance:
  qualifying > 0 -> "🔴 WARNING — CoralTicker daily email digest did not send today
    (2026-06-30 UTC). There were 164 coral drops that should have gone out ..."
    (drops existed and no send = broken, go look at the discord-digest run + Resend).
  qualifying == 0 -> "🟢 CoralTicker daily email digest: nothing sent today
    (2026-06-30 UTC) — and there were 0 coral drops, so this is expected."
    (nothing to send = correctly quiet, no action).

The qualifying-drops count mirrors lib/email/digest.ts:fetchRows + suppressBulkDump
(get_listing_lead_event 24h window, JOIN vendor_listings, exclude equipment/invert
categories NULL-safely, drop the bulk_cluster just-listed dump cohort). It is a
disambiguation aid, not the send path; kept in lockstep with the digest by the comment
markers below.

EXIT CODE: 0 whether the row is present OR absent-with-alert-posted — the Slack ping IS
the signal, so a non-zero exit (which would also trip the workflow's own failure alert)
would double-signal. A non-zero exit is reserved for the watchdog itself failing (DB
unreachable, webhook non-2xx via post_slack), which the workflow's if: failure() step
surfaces separately.

Run:
  python -m scripts.email_digest_watchdog            # CI / scheduled
  python -m scripts.email_digest_watchdog            # locally after `. .env` (NEON + SLACK from env)
"""

from __future__ import annotations

import logging

from scrapers.common.cohort_signal import post_slack
from scrapers.common.db import get_conn

logger = logging.getLogger(__name__)

# Mirrors lib/queries/category-exclusion.ts EXCLUDED_CATEGORIES — the hidden-category
# denylist the digest applies. Kept in lockstep by hand (two-runtime constant: TS for the
# send path, here for the watchdog count). Adding a hidden category is a one-line edit in
# BOTH places.
_EXCLUDED_CATEGORIES = ["equipment", "invert"]

# Qualifying-drops count — the same set lib/email/digest.ts:fetchRows builds, minus the
# render. get_listing_lead_event(NULL, 24, NULL, NULL) is the fleet-wide 24h lead-event
# source; the JOIN re-applies the NULL-safe category exclusion (the RPC doesn't filter
# category internally) and drops the bulk_cluster just-listed dump cohort (suppressBulkDump).
_QUALIFYING_DROPS_SQL = """
    SELECT count(*)::int AS n
    FROM get_listing_lead_event(NULL, 24, NULL, NULL) le
    JOIN vendor_listings vl ON vl.id = le.id
    WHERE (vl.category IS NULL OR vl.category <> ALL(%s::text[]))
      AND NOT (vl.bulk_cluster AND le.event = 'just-listed')
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Today's UTC date — the email_digest_runs fire-once key (UTC, matching the
            # digest's 13:00 UTC fire and its toISOString() key). now() is timestamptz;
            # AT TIME ZONE 'UTC' yields the UTC wall-clock, ::date its calendar day.
            cur.execute(
                "SELECT (now() AT TIME ZONE 'UTC')::date AS utc_date, "
                "       (SELECT sent_count FROM email_digest_runs "
                "        WHERE sent_date = (now() AT TIME ZONE 'UTC')::date) AS sent_count"
            )
            row = cur.fetchone()
            utc_date = row["utc_date"]
            sent_count = row["sent_count"]

            if sent_count is not None:
                logger.info(
                    "email_digest_runs row present for %s (sent %s); digest healthy",
                    utc_date,
                    sent_count,
                )
                return 0

            # No row — could be broken (drops existed, none sent) or correctly quiet
            # (zero qualifying drops / zero recipients). Count qualifying drops to
            # disambiguate in the alert text.
            cur.execute(_QUALIFYING_DROPS_SQL, (_EXCLUDED_CATEGORIES,))
            qualifying = cur.fetchone()["n"]

    if qualifying > 0:
        message = (
            f"🔴 WARNING — CoralTicker daily email digest did not send today ({utc_date} UTC).\n"
            f"There were {qualifying} coral drops that should have gone out, but no successful send was recorded — the digest likely didn't fire or failed silently, and subscribers probably missed today's email.\n"
            f"What to check: the latest discord-digest workflow run + the Resend dashboard. To re-send: run scripts/run_email_digest.ts.\n"
            f"(Automated email-digest watchdog — you only hear from it when something looks wrong.)"
        )
    else:
        message = (
            f"🟢 CoralTicker daily email digest: nothing sent today ({utc_date} UTC) — and there were 0 coral drops, so this is expected.\n"
            f"No action needed. (If you did expect drops today, a scraper may be down — worth a glance.)\n"
            f"(Automated email-digest watchdog.)"
        )
    logger.warning(message)
    post_slack(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
