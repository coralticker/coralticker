"""CTK-161 D-3 — INV-01 Python mirror of the channel-parity data-row renderer.

The web component <DataRow> (components/ui/data-row.tsx) renders the canonical
em-dash data row to DOM; lib/format/data-row.ts:formatDataRow() renders the SAME
logical content as plain text for non-DOM channels (email digest, Discord embed,
push body). INV-01 binds them to one shape: same field order, same labels, same
em-dash separator, same value-kind text.

The Python content consumers (CTK-161 IG captions, CTK-163 TikTok/YT frames)
cannot import the TS function across the language boundary. So INV-01 here binds
the OUTPUT SHAPE, not the function call: this module is a drift-guarded mirror of
formatDataRow() + formatRelativeTime(), pinned to the TS source of truth by a
committed golden fixture (lib/format/data-row-golden.json) that BOTH a TS test
and a Python test assert against. Same precedent as ig_select.py's MIRROR_HOST
const + drift-guard test — shape parity enforced by a test, not re-implemented by
feel.

A DataRowField mirrors the TS interface as a plain dict (so the golden JSON loads
directly into both runtimes):

    {"label": str, "value": <value>}

where <value> is either a bare str or a discriminated dict carrying "kind":
    {"kind": "relative-time", "timestamp": <iso str>}
    {"kind": "price-drop-new", "oldValue": str, "newValue": str}
    {"kind": "vendor-markdown", "oldValue": str, "newValue": str}
    {"kind": "invalidated", "value": str}
    {"kind": "italic", "value": str}

This module is pure — no DB, no network, no env. Tests drive it directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Mirrors lib/format/relative-time.ts MONTH_NAMES. Locale-independent month
# formatting so the >= 7d absolute branch agrees with the TS source byte-for-byte
# (when both run in the same timezone — see format_relative_time's note).
MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _epoch_ms(value: str | datetime) -> int:
    """Epoch milliseconds for an ISO-8601 string or a datetime, mirroring JS
    `new Date(x).getTime()`. Whole-second timestamps (the DB-written shape) land
    exactly: epoch-seconds * 1000 is within float64 integer-exactness at these
    magnitudes. A naive datetime is assumed UTC (the data plane is UTC-only)."""
    if isinstance(value, str):
        # fromisoformat handles the trailing 'Z' on Python 3.11+.
        dt = datetime.fromisoformat(value)
    else:
        dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(round(dt.timestamp() * 1000))


def format_relative_time(timestamp: str | datetime, now: datetime) -> str:
    """Mirror of lib/format/relative-time.ts:formatRelativeTime(). Format ladder
    per branding-guide.md §"Time format":
        < 1h    -> "N minute(s) ago"  (singular at N == 1)
        < 24h   -> "N hour(s) ago"
        < 7d    -> "N day(s) ago"
        >= 7d   -> "MMM D"

    Negative diffs (future timestamps, SSR/client clock skew) clamp to 0; the
    < 1h minute floor clamps to 1 — identical to the TS source.

    NOTE: the >= 7d branch reads month/day in UTC on the Python side (the data
    plane is UTC-only; the caption cron + CI run UTC). The TS source uses local
    getters — correct for the browser <RelativeTime> DOM path (users want their
    local date), and UTC-resolving for the server formatDataRow path on Vercel —
    so production parity holds. The golden fixture deliberately exercises only the
    < 7d relative branches (pure epoch arithmetic, identical across runners); the
    >= 7d branch is not pinned, since its TS output is surface-dependent by
    design."""
    past_ms = _epoch_ms(timestamp)
    now_ms = _epoch_ms(now)
    diff_sec = max(0, (now_ms - past_ms) // 1000)

    if diff_sec < 3_600:
        minutes = max(1, diff_sec // 60)
        return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
    if diff_sec < 86_400:
        hours = diff_sec // 3_600
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    if diff_sec < 604_800:
        days = diff_sec // 86_400
        return "1 day ago" if days == 1 else f"{days} days ago"
    # >= 7d absolute branch — UTC-pinned (data plane is UTC; runner-independent).
    utc_dt = datetime.fromtimestamp(past_ms / 1000.0, tz=timezone.utc)
    return f"{MONTH_NAMES[utc_dt.month - 1]} {utc_dt.day}"


def _format_value(value, now: datetime) -> str:
    """Mirror of lib/format/data-row.ts:formatValue(). Exhaustive over the
    DataRowFieldValue discriminated union; raises on an unknown kind so a new TS
    value-kind that lands without a Python branch fails loudly (the drift-guard
    posture), never silently mis-renders."""
    if isinstance(value, str):
        return value
    kind = value["kind"]
    if kind == "relative-time":
        return format_relative_time(value["timestamp"], now)
    if kind == "invalidated":
        # DOM-only strikethrough on the TS side; non-DOM channels carry the bare
        # value (the OOS semantic rides a separate row-state-marker downstream).
        return value["value"]
    if kind == "price-drop-new":
        # No connective words — struck old value + emphasized new value already
        # read "old -> new" (branding-guide §"State markers"). Adjacency-with-a-
        # space mirrors the web <DataRow>.
        return f"{value['oldValue']} {value['newValue']}"
    if kind == "vendor-markdown":
        # Shares price-drop-new's field-level shape (identical reefer semantic).
        return f"{value['oldValue']} {value['newValue']}"
    if kind == "italic":
        # DOM-only emphasis (<em>) on the TS side; non-DOM carries bare text.
        return value["value"]
    raise ValueError(f"format_data_row: unhandled value kind {kind!r}")


def format_data_row(fields: list[dict], now: datetime) -> str:
    """Mirror of lib/format/data-row.ts:formatDataRow(). Renders a DataRowField
    list to the canonical em-dash plain-text row: each field as "Label. value",
    joined by " — ". Field order and labels are caller-supplied (the listing-line
    contract); this function pins the RENDER mechanism, which is what INV-01
    binds across the language boundary."""
    return " — ".join(
        f"{field['label']}. {_format_value(field['value'], now)}" for field in fields
    )
