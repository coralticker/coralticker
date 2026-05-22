"""Stage 5 (Diff) + Stage 6 (Persist) per arch §2.1 + §2.2. Bulk-load existing
listings once at stage-5 start, classify per-item, then bulk-write changes.
500-2000 items × (1 SELECT + 1 UPSERT + 1 INSERT) per scrape becomes 1 SELECT +
N upserts + M inserts — keeps round-trips bounded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Literal

import psycopg

from scrapers.common import images as image_pipeline
from scrapers.common.matcher import MatchResult

log = logging.getLogger(__name__)


Decision = Literal["new", "price_changed", "restocked", "oos", "unchanged"]


@dataclass
class ItemDecision:
    item: dict
    decision: Decision
    existing_id: int | None = None  # set on update paths; None for "new"
    # CTK-025: matcher result attached by run.py stage 5.5. None = matcher
    # didn't run (preserve existing match fields in UPSERT — payload omits
    # match columns; the absent-column = keep-existing contract is preserved
    # via per-row dynamic ON CONFLICT DO UPDATE in _upsert_listing_row).
    # Non-None = write all four match fields (named_coral_id,
    # match_confidence, match_method, matched_at) on the UPSERT row, even if
    # all four are null (stage 7 no-match — explicit clear).
    match_result: MatchResult | None = None


@dataclass
class Counters:
    seen: int = 0
    new: int = 0
    price_changed: int = 0
    restocked: int = 0
    oos: int = 0


def classify(items: Iterable[dict], existing_by_url: dict[str, dict]) -> list[ItemDecision]:
    """Apply the §2.2 diff rule: for each parsed item, look up by product_url
    and classify. Returns ItemDecision list — caller iterates to persist."""
    decisions: list[ItemDecision] = []
    for item in items:
        url = item["product_url"]
        existing = existing_by_url.get(url)
        if existing is None:
            decisions.append(ItemDecision(item=item, decision="new"))
            continue
        old_price = _to_decimal(existing.get("current_price"))
        new_price = _to_decimal(item.get("current_price"))
        if old_price != new_price:
            decisions.append(ItemDecision(item=item, decision="price_changed", existing_id=existing["id"]))
        elif item["in_stock"] and not existing["in_stock"]:
            decisions.append(ItemDecision(item=item, decision="restocked", existing_id=existing["id"]))
        elif not item["in_stock"] and existing["in_stock"]:
            decisions.append(ItemDecision(item=item, decision="oos", existing_id=existing["id"]))
        else:
            decisions.append(ItemDecision(item=item, decision="unchanged", existing_id=existing["id"]))
    return decisions


def counters_from(decisions: list[ItemDecision]) -> Counters:
    c = Counters(seen=len(decisions))
    for d in decisions:
        if d.decision == "new":
            c.new += 1
        elif d.decision == "price_changed":
            c.price_changed += 1
        elif d.decision == "restocked":
            c.restocked += 1
        elif d.decision == "oos":
            c.oos += 1
    return c


@dataclass
class MirrorTask:
    """Phase B work item — a row whose image_url should be populated by a
    mirror() round-trip after Phase A has committed scrape state. Built in
    Phase A for both NEW rows (no existing image_url yet) and EXISTING rows
    with image_url IS NULL (catch-up from prior partial-mirror runs)."""
    product_url: str           # absolute URL (FK lookup key against vendor_listings)
    vendor_image_url: str      # source URL to fetch
    listing_id: int | None     # set when known (existing rows); None for NEW (resolved after Phase A upsert)


def persist_phase_a(
    conn: psycopg.Connection,
    vendor_row: dict,
    decisions: list[ItemDecision],
    existing_by_url: dict[str, dict],
    run_id: int,
) -> list[MirrorTask]:
    """Phase A — synchronous, fast, defines 'scrape success'. Bulk UPSERT
    vendor_listings; touch unchanged rows; resolve listing_id; bulk INSERT
    price_history on (price, stock) change. Returns the Phase B mirror queue
    (mirror-strategy rows whose image_url is NULL after Phase A).

    Per arch §3.2 + CTK-023 Call 2: NO matcher call between stage 5 and stage 6
    in CTK-024 — Pacific East ships matcher-naive. Retro-fit when CTK-025
    lands the inline scaffold (one method-call addition between Phase A
    classify-and-build and Phase A upsert).

    The phase split is forced by image-fetch latency: ~500ms per mirror() call
    × first-run NEW listing count (PE ~2500-3000) = workflow timeout territory
    if mirror runs inline. Phase A keeps DB-write latency bounded; Phase B
    runs after status='success' so an image-mirror timeout no longer loses
    the underlying scrape data per CTK-019 #55 ('image-only failure does NOT
    fail the listing row').
    """
    vendor_id = vendor_row["id"]
    base_url = vendor_row["base_url"].rstrip("/")
    image_strategy = vendor_row.get("image_strategy", "mirror")

    now = datetime.now(timezone.utc).isoformat()

    upserts: list[dict] = []
    history: list[dict] = []
    touch_ids: list[int] = []
    mirror_queue: list[MirrorTask] = []

    for d in decisions:
        item = d.item
        # item["product_url"] is now ABSOLUTE per parse_shopify._normalize_product
        # (Session 2 fix — was relative in Session 1, which would have misclassified
        # every existing listing as 'new' on the next-day scrape).
        product_url = item["product_url"]

        # Hotlink strategy is fast (no I/O) — set image_url in Phase A on NEW
        # rows only (existing rows preserve their image_url; we don't refresh
        # hotlinks on every scrape). Mirror strategy defers to Phase B for
        # both NEW and EXISTING-with-NULL-image_url rows; image_url is OMITTED
        # from the upsert payload so the column default (NULL) lands on NEW
        # and existing image_url is preserved on UPDATE — the absent-column =
        # keep-existing contract is preserved via per-row dynamic ON CONFLICT
        # DO UPDATE in _upsert_listing_row (writes only payload-present cols).
        hotlink_url: str | None = None
        if image_strategy == "hotlink" and d.decision == "new" and item.get("vendor_image_url"):
            hotlink_url = item["vendor_image_url"]

        # Build the Phase B queue — mirror-strategy only, vendor_image_url present,
        # AND (NEW row OR existing row with NULL image_url for catch-up).
        if image_strategy != "hotlink" and item.get("vendor_image_url"):
            existing = existing_by_url.get(product_url)
            existing_image_url = existing.get("image_url") if existing else None
            if d.decision == "new" or not existing_image_url:
                mirror_queue.append(MirrorTask(
                    product_url=product_url,
                    vendor_image_url=item["vendor_image_url"],
                    listing_id=d.existing_id,  # None for NEW; resolved after upsert
                ))

        if d.decision == "unchanged":
            touch_ids.append(d.existing_id)  # type: ignore[arg-type]
            continue

        row = {
            "vendor_id": vendor_id,
            "vendor_sku": item.get("vendor_sku"),
            "product_url": product_url,
            "raw_title": item["raw_title"],
            "normalized_title": item["normalized_title"],
            "current_price": _decimal_to_str(item.get("current_price")),
            "currency": item.get("currency", "USD"),
            "in_stock": item["in_stock"],
            "category": item.get("category"),
            "lineage_flag": item.get("lineage_flag", "unknown"),
            "last_seen_at": now,
        }
        # first_seen_at is omitted from every payload: the absent-column =
        # keep-existing contract via per-row dynamic ON CONFLICT DO UPDATE in
        # _upsert_listing_row means UPDATE never touches first_seen_at when
        # it's not in the payload. DB DEFAULT now() handles INSERT; trigger
        # preserve_first_seen_at is the belt-and-suspenders lock on UPDATE.
        if d.decision == "new" and hotlink_url is not None:
            row["image_url"] = hotlink_url
        if d.decision == "price_changed":
            row["last_price_changed_at"] = now

        # CTK-025: write the four matcher fields when run.py attached a
        # match_result. Always-explicit on 'new' rows (run.py invokes the
        # matcher); omitted on update-path rows so the existing match fields
        # are preserved via per-row dynamic ON CONFLICT DO UPDATE in
        # _upsert_listing_row (no clobber on price/stock-only changes).
        if d.match_result is not None:
            row["named_coral_id"] = d.match_result.named_coral_id
            row["match_confidence"] = d.match_result.match_confidence
            row["match_method"] = d.match_result.match_method
            row["matched_at"] = d.match_result.matched_at

        upserts.append(row)

        # price_history INSERT on (price, stock) change OR on new — captures the
        # baseline observation per arch §1.5 write rule.
        if d.decision in ("new", "price_changed", "restocked", "oos"):
            history.append({
                "price": _decimal_to_str(item.get("current_price")),
                "in_stock": item["in_stock"],
                "scraper_run_id": run_id,
                "_product_url": product_url,  # join key; stripped before INSERT
            })

    # UPSERT vendor_listings per-row with dynamic column list — preserves the
    # absent-column = keep-existing contract via per-row dynamic ON CONFLICT
    # DO UPDATE in _upsert_listing_row, by including only the row's actual
    # keys in both the INSERT column list and the ON CONFLICT DO UPDATE SET
    # clause. Per-row execute keeps the heterogeneous-column path clean
    # (CTK-025 match-field preservation rule + CTK-024 image_url-on-NEW-only
    # rule both ride on this); RETURNING id, product_url builds the
    # listing_id-by-url map inline (CTK-024 Session 5 — replaces the
    # post-upsert SELECT round-trip).
    id_by_url: dict[str, int] = {}
    if upserts:
        with conn.cursor() as cur:
            for row in upserts:
                lid, purl = _upsert_listing_row(cur, row)
                id_by_url[purl] = lid

    # Touch unchanged rows (last_seen_at only). Single chunked UPDATE per
    # 1000-row batch via ANY(%s); psycopg parameterizes the array as a single
    # bind — no URL-length pressure (the chunk-of-500 cap under supabase-py
    # was a PostgREST URL-length workaround, not a SQL constraint).
    if touch_ids:
        with conn.cursor() as cur:
            for chunk in _chunks(touch_ids, 1000):
                cur.execute(
                    "UPDATE vendor_listings SET last_seen_at = %s WHERE id = ANY(%s)",
                    (now, chunk),
                )

    # Hand listing_ids back to the mirror queue.
    for t in mirror_queue:
        if t.listing_id is None:
            t.listing_id = id_by_url.get(t.product_url)

    # Insert price_history. Homogeneous columns — executemany pipelines the
    # batch cleanly.
    if history:
        history_rows = []
        for h in history:
            lid = id_by_url.get(h["_product_url"])
            if lid is None:
                log.warning("price_history: no listing_id for %s — skip", h["_product_url"])
                continue
            history_rows.append((lid, h["price"], h["in_stock"], h["scraper_run_id"]))
        if history_rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO price_history (listing_id, price, in_stock, scraper_run_id) "
                    "VALUES (%s, %s, %s, %s)",
                    history_rows,
                )

    log.info(
        "Phase A complete: %d upserts + %d touches + %d history rows; %d Phase B mirrors queued",
        len(upserts), len(touch_ids), len(history), len(mirror_queue),
    )
    return mirror_queue


def persist_phase_b(conn: psycopg.Connection, vendor_row: dict, mirror_queue: list[MirrorTask]) -> tuple[int, int]:
    """Phase B — best-effort, per-row, fail-soft. Iterates the Phase A mirror
    queue: for each entry, attempt mirror() + UPDATE vendor_listings.image_url.
    Per-row exceptions log a WARNING and continue; no row fails the whole run.

    Returns (succeeded, failed) counts for the orchestrator log.

    Phase B is called AFTER scraper_runs.status has been finalized as 'success'.
    A workflow-timeout hard-kill mid-Phase-B leaves successful mirrors landed
    + remaining queue entries un-processed; subsequent runs catch them up via
    the existing-row-with-NULL-image_url path (db.fetch_existing_listings now
    returns image_url so the next Phase A can re-queue them).

    Hotlink strategy never reaches Phase B — those rows have image_url set in
    Phase A's upsert payload directly (no I/O latency cost).
    """
    if not mirror_queue:
        return (0, 0)

    vendor_slug = vendor_row["slug"]
    succeeded = 0
    failed = 0

    for task in mirror_queue:
        if task.listing_id is None:
            # Couldn't resolve listing_id post-upsert — log and move on. Should
            # be rare; signals an upsert that quietly didn't land or a stale
            # vendor_listings index. Either way, the next scrape will re-queue.
            log.warning("Phase B: no listing_id resolved for %s — skip", task.product_url)
            failed += 1
            continue
        try:
            url = image_pipeline.mirror(vendor_slug, task.product_url, task.vendor_image_url)
            if url is None:
                # mirror() already logged the failure cause (network / non-200 /
                # upload error) per CTK-019 #55. Leave image_url as NULL; next
                # scrape's Phase A re-queues this row.
                failed += 1
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE vendor_listings SET image_url = %s WHERE id = %s",
                    (url, task.listing_id),
                )
            succeeded += 1
        except Exception as e:  # noqa: BLE001 — fail-soft per CTK-019 #55; image-only error never fails the run
            log.warning("Phase B mirror failed for listing_id=%s (%s): %s", task.listing_id, task.product_url, e)
            failed += 1

    log.info("Phase B complete: %d mirrors succeeded, %d failed (queue size %d)", succeeded, failed, len(mirror_queue))
    return (succeeded, failed)


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _to_decimal(v) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def _decimal_to_str(v) -> str | None:
    """PostgREST/JSON serialization — Decimal → string preserves precision
    without float-rounding noise. The numeric(10,2) column accepts the string."""
    d = _to_decimal(v)
    if d is None:
        return None
    return f"{d:.2f}"


# CTK-043 cut-1: column allowlist for the dynamic per-row UPSERT below.
# Pinned to the union of columns persist_phase_a may emit per the diff-rule
# bucketing above (base 11 + image_url + last_price_changed_at + the four
# CTK-025 match fields). Defense-in-depth against accidental SQL-shape drift
# if a future caller passes a stray key in the row dict.
_UPSERT_ALLOWED_COLS = frozenset({
    "vendor_id",
    "vendor_sku",
    "product_url",
    "raw_title",
    "normalized_title",
    "current_price",
    "currency",
    "in_stock",
    "category",
    "lineage_flag",
    "last_seen_at",
    "image_url",
    "last_price_changed_at",
    "named_coral_id",
    "match_confidence",
    "match_method",
    "matched_at",
})


def _upsert_listing_row(cur, row: dict) -> tuple[int, str]:
    """Single-row UPSERT into vendor_listings. Column list driven by the
    row's actual keys so the ON CONFLICT DO UPDATE SET clause touches only
    columns the payload provided — preserves PostgREST upsert's "absent =
    keep existing" semantics that CTK-025 (match-field preservation on
    price/stock-only changes) and CTK-024 (image_url-on-NEW-only) both
    depend on. Returns (id, product_url) from RETURNING.
    """
    cols = [c for c in row.keys() if c in _UPSERT_ALLOWED_COLS]
    if len(cols) != len(row):
        unknown = set(row.keys()) - _UPSERT_ALLOWED_COLS
        raise RuntimeError(f"_upsert_listing_row: unknown column(s) in row: {sorted(unknown)}")
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    update_set = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c not in ("vendor_id", "product_url")
    )
    sql = (
        f"INSERT INTO vendor_listings ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (vendor_id, product_url) DO UPDATE SET {update_set} "
        f"RETURNING id, product_url"
    )
    cur.execute(sql, [row[c] for c in cols])
    result = cur.fetchone()
    return (result["id"], result["product_url"])
