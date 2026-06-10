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

MarkdownAction = Literal["set", "clear", "keep"]


def _markdown_transition(existing_compare_at, item_compare_at) -> MarkdownAction:
    """CTK-124 F8 — classify the markdown_started_at write for one row.

    Presence-based episode semantics against the DB-side value
    (fetch_existing_listings now returns compare_at_price) vs. the parsed
    item's value:

      NULL -> non-NULL  => "set"   (episode onset; write now())
      non-NULL -> NULL  => "clear" (vendor pulled the slash; write NULL)
      otherwise         => "keep"  (no episode boundary — mid-episode value
                                    drift does NOT reset the onset, and
                                    never-marked rows stay NULL)

    NEW rows pass existing_compare_at=None: markdown at first sight is a
    NULL -> non-NULL transition by construction, so onset = now per the
    plan's cold-start posture. The trigger is compare_at_price PRESENCE,
    not the compare_at > current inequality — the reader-side RPC
    (migration 0033 arm 2) applies the inequality; capture just attests
    when the episode began. Decision #7 holds: no price_history write for
    markdown events; this column is the only persistence.
    """
    had = existing_compare_at is not None
    has = item_compare_at is not None
    if has and not had:
        return "set"
    if had and not has:
        return "clear"
    return "keep"


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


def classify(
    items: Iterable[dict],
    existing_by_url: dict[str, dict],
    *,
    cohort_oos_at_persist: bool = False,
    filtered_urls: set[str] | None = None,
) -> tuple[list[ItemDecision], list[ItemDecision]]:
    """Apply the §2.2 diff rule: for each parsed item, look up by product_url
    and classify. Returns a (per_item_decisions, cohort_oos_decisions) tuple.

    CTK-094 §3 cohort-comparison-OOS at persist (D-1 ratified 2026-05-31).
    The §2.2 diff today iterates only products PRESENT in the scrape, which
    leaves stale `in_stock=true` rows on vendors that drop sold-out items
    pre-diff (POTO `in_stock_only`, AquaSD BC Stencil hides OOS, TG Magento
    hides OOS). On opt-in (`cohort_oos_at_persist=True`), classify does one
    extra pass after the per-item loop: URLs that were `in_stock=true` in
    `existing_by_url` AND are absent from the current scrape's seen-URL set
    flip to `in_stock=false` AND emit `ItemDecision(decision="oos",
    existing_id=...)` in the second tuple element. The caller (run.py)
    gates the second list on the canary outcome — short-circuit per §3 so
    a SchemaChangeError / canary-tripped / config-error run doesn't mass-
    fire false OOS on a partial parse.

    Per the directive: build `seen_urls` as a set DURING the existing per-
    item loop (single pass over `items`). Do NOT call `set(items)` — if
    `items` is a generator, the second iteration would be empty and the
    cohort pass would mass-fire every existing in-stock row as absent.

    Byte-equivalent skip path on `cohort_oos_at_persist=False`: the seen_urls
    set is still built (cheap dict-add per item) but the cohort pass below
    the loop short-circuits, returning an empty second list. The 8 stable-
    catalog vendors (PE/WWC/TSA/JF/BC/UC/Vivid/RC) stay byte-identical —
    `per_item_decisions` matches the pre-CTK-094 return list and the empty
    cohort list extends to a no-op at the caller.

    CTK-106 admitted-set contract (decision #83; supersedes the CTK-094
    fold-#4 exclusion): `in_stock=true` is asserted only while a row is in
    the vendor's current admitted set — parsed from the feed AND passed the
    YAML category filter. A previously-admitted row that exits the admitted
    set flips OOS through this pass for EITHER cause: vendor-recat (vendor
    moved the item to a non-allowlisted bucket; may still be buyable
    on-vendor) or operator-tighten (YAML filter edit denies a class we no
    longer track). Both mean CoralTicker has stopped observing the row, and
    a frozen `in_stock=true` at a stale price overstates (the trust-floor
    failure class) where a conservative OOS merely understates. So
    `filtered_urls` no longer gates membership — it feeds the
    filtered-stuck flip count in the log line only. Defaulted to None
    (treated as empty set); empty-set runs are byte-equivalent to the
    pre-CTK-106 predicate. Flips are one-shot and self-terminating: once
    `in_stock=false`, the `existing.get("in_stock")` guard skips the row
    on every later run.

    Guard routing (CTK-106 D-3): filtered-flips share the Stage-5.65 flip
    cap + CTK-137 K=3 convergence with the rest of the absent-set — one
    mass-flip guard covers the overbroad-YAML-edit failure mode (load-time
    schema validation catches malformed configs, not overbroad ones).
    Named limitation: a >cap tightening on a high-churn vendor may never
    K-converge (ordinary delist churn perturbs the absent-set hash each
    run, breaking the K-stable chain); the operator one-shot
    `cohort_flip_cap` raise is the documented fast-path — pair any
    tightening expected to deny >25% of a vendor's in-stock rows with a
    one-run cap raise in the same commit.

    Flap honesty (CTK-106 D-5): a vendor oscillating an item across the
    filter boundary (rotating promo product_types) produces OOS/restock
    cycles — the flip here, the recovery via the per-item `restocked`
    branch on readmission. Accepted: each state is honest at observation
    time; the status-quo alternative (frozen stale-available at the
    pre-promo price) is worse wrong-info.
    """
    _filtered = filtered_urls or set()
    per_item_decisions: list[ItemDecision] = []
    seen_urls: set[str] = set()
    for item in items:
        url = item["product_url"]
        seen_urls.add(url)
        existing = existing_by_url.get(url)
        if existing is None:
            per_item_decisions.append(ItemDecision(item=item, decision="new"))
            continue
        old_price = _to_decimal(existing.get("current_price"))
        new_price = _to_decimal(item.get("current_price"))
        if old_price != new_price:
            per_item_decisions.append(ItemDecision(item=item, decision="price_changed", existing_id=existing["id"]))
        elif item["in_stock"] and not existing["in_stock"]:
            per_item_decisions.append(ItemDecision(item=item, decision="restocked", existing_id=existing["id"]))
        elif not item["in_stock"] and existing["in_stock"]:
            per_item_decisions.append(ItemDecision(item=item, decision="oos", existing_id=existing["id"]))
        else:
            per_item_decisions.append(ItemDecision(item=item, decision="unchanged", existing_id=existing["id"]))

    cohort_oos_decisions: list[ItemDecision] = []
    if cohort_oos_at_persist:
        # Cohort-absent pass — URLs in DB with in_stock=true that exited
        # the admitted set this scrape (absent from the feed OR rejected by
        # the parser filter — CTK-106 admitted-set contract, see docstring).
        # Synthetic ItemDecision carries only the minimal shape that
        # persist_phase_a's decision=="oos" branch touches: product_url for
        # join + in_stock=false. Other vendor_listings columns stay at
        # their existing values via the direct UPDATE-by-id path (see
        # persist_phase_a synthetic branch).
        filtered_stuck = 0
        for url, existing in existing_by_url.items():
            if existing.get("in_stock") and url not in seen_urls:
                if url in _filtered:
                    filtered_stuck += 1
                cohort_oos_decisions.append(ItemDecision(
                    item={
                        "product_url": url,
                        "in_stock": False,
                        # current_price preserves on UPSERT (column absent from
                        # _UPSERT_ALLOWED_COLS payload when not provided), but
                        # price_history INSERT uses the item's current_price
                        # at diff.py L207-211 — pull from existing to record
                        # the last-known price alongside the stock flip.
                        "current_price": existing.get("current_price"),
                        # raw_title / normalized_title / category preserve via
                        # the absent-column rule too; omit from the synthetic
                        # item to avoid clobbering existing values.
                    },
                    decision="oos",
                    existing_id=existing["id"],
                ))
        if filtered_stuck:
            # CTK-106 D-2 observability — filtered-stuck flips are admitted-
            # set exits the retired fold-#4 predicate would have spared.
            log.info(
                "cohort absent-pass: %d of %d flips are filtered-stuck (parser-rejected, exited admitted set)",
                filtered_stuck, len(cohort_oos_decisions),
            )

    return per_item_decisions, cohort_oos_decisions


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

    CTK-116 D-2: all writes run inside one conn.transaction() block — a
    mid-persist exception rolls the data plane back to zero footprint
    instead of stranding a partial upsert set under autocommit. The caller
    (run.py Stage 6) additionally skips this function entirely on canary
    trip (CTK-116 D-1) — failed runs leave no vendor_listings /
    price_history footprint by either path.

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
    # CTK-100 Wave-2 hotfix 2026-06-01: was `touch_ids: list[int]`. Carrying
    # the per-row compare_at_price payload through the unchanged-row branch
    # so the chunked UPDATE below can write both last_seen_at AND
    # compare_at_price. Wave-2 ship-day blind spot: F6's UPSERT-path wiring
    # at L275-287 never fires for decision=='unchanged' rows (the dominant
    # case for steady-state scrapes), so TG run 765 wrote 0 markdowns on
    # 348 listings_seen including all 4 audit-confirmed live markdowns
    # (Beginner Coral Pack / Feeling Lucky 10 / Feeling Lucky 5 / Leopard
    # Discosoma). See [[feedback_capture_path_unchanged_blind_spot]] for the
    # rule this incident established.
    touch_payloads: list[dict] = []
    cohort_oos_ids: list[int] = []  # CTK-094 — direct UPDATE path; see below
    mirror_queue: list[MirrorTask] = []
    # Pre-declared so the CTK-094 cohort branch can pre-populate
    # `id_by_url[product_url] = existing_id` before the UPSERT loop runs;
    # the price_history INSERT at the bottom resolves listing_id by URL
    # join, so cohort rows need their id in the map even though they skip
    # the UPSERT path.
    id_by_url: dict[str, int] = {}

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
            # CTK-100 Wave-2 hotfix: carry compare_at_price into the touch
            # path so the chunked UPDATE below writes the markdown reference
            # alongside last_seen_at. Without this, F6's UPSERT-path wiring
            # never reaches the dominant steady-state case (rows unchanged
            # between scrapes). Write-amplification: the UPDATE writes
            # compare_at_price on every unchanged row even when it hasn't
            # changed — acceptable at current scale (~350-3000 rows/vendor/
            # scrape × daily cron); revisit if write-side cost surfaces.
            #
            # CTK-124 F8: markdown_action rides the same payload so the
            # chunked UPDATE can write/clear markdown_started_at on episode
            # boundaries. The unchanged path is the DOMINANT capture path —
            # a row whose only change is compare_at_price appearing/vanishing
            # classifies as 'unchanged' (price + stock identical), exactly
            # the Wave-2 blind-spot class per
            # feedback_capture_path_unchanged_blind_spot.
            existing = existing_by_url.get(product_url) or {}
            touch_payloads.append({
                "id": d.existing_id,
                "compare_at_price": _decimal_to_str(item.get("compare_at_price")),
                "markdown_action": _markdown_transition(
                    existing.get("compare_at_price"), item.get("compare_at_price")
                ),
            })
            continue

        # CTK-094 cohort-OOS synthetic decisions take a direct UPDATE path
        # rather than UPSERT. The UPSERT/ON CONFLICT pattern can't preserve
        # NOT NULL columns from the existing row — Postgres evaluates NOT NULL
        # constraints on the INSERT-row-build BEFORE ON CONFLICT routes to
        # DO UPDATE, so a synthetic row missing raw_title (NOT NULL, no
        # default) fails before the conflict can resolve. existing_id is
        # known from classify (URL was in existing_by_url with in_stock=True),
        # so we batch a `UPDATE ... WHERE id = ANY(%s)` instead. Discriminator:
        # synthetic items omit `raw_title` (real parser items always carry it
        # per the parser dict shape lock at parse_shopify._normalize_product +
        # parse_bigcommerce._parse_one_page + tidal_gardens._parse_one_page).
        # price_history INSERT still records the (last-known-price, in_stock=
        # False) row; pre-populate id_by_url so the join below resolves.
        is_cohort_oos_synthetic = "raw_title" not in item
        if is_cohort_oos_synthetic:
            cohort_oos_ids.append(d.existing_id)  # type: ignore[arg-type]
            id_by_url[product_url] = d.existing_id  # type: ignore[assignment]
            history.append({
                "price": _decimal_to_str(item.get("current_price")),
                "in_stock": False,
                "scraper_run_id": run_id,
                "_product_url": product_url,
            })
            continue

        row = {
            "vendor_id": vendor_id,
            "vendor_sku": item.get("vendor_sku"),
            "product_url": product_url,
            "raw_title": item["raw_title"],
            "normalized_title": item["normalized_title"],
            "current_price": _decimal_to_str(item.get("current_price")),
            "compare_at_price": _decimal_to_str(item.get("compare_at_price")),  # CTK-100 Wave-2 F6 — turns capture into writes. item.get returns None cleanly when parsers don't set the key (e.g., pre-Wave-2 BC/Magento scrapes still in-flight); _decimal_to_str returns None for None input.
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

        # CTK-124 F8 — markdown_started_at on the UPSERT path (new /
        # price_changed / restocked / oos). "set" writes now(); "clear"
        # writes an explicit NULL; "keep" OMITS the key so the absent-
        # column = keep-existing contract in _upsert_listing_row preserves
        # the live onset (mid-episode value drift never resets it). NEW
        # rows have no existing entry, so markdown-at-first-sight resolves
        # to "set" through the same helper. The cohort-OOS synthetic branch
        # above deliberately skips this wiring: those rows are ABSENT from
        # the scrape, so there is no compare_at_price observation to attest
        # — onset stays untouched and the reader's in_stock predicate
        # (INV-05) keeps them off /deals anyway.
        existing = existing_by_url.get(product_url)
        md_action = _markdown_transition(
            existing.get("compare_at_price") if existing else None,
            item.get("compare_at_price"),
        )
        if md_action == "set":
            row["markdown_started_at"] = now
        elif md_action == "clear":
            row["markdown_started_at"] = None

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

    # CTK-116 D-2 — Phase A atomicity boundary. The connection is
    # autocommit=True (db.py CTK-043 cut-1), so without an explicit
    # transaction an exception at row N of the write blocks below strands
    # N committed rows while the outer catch finalizes status='failed' —
    # partial footprint, same failed-run write-integrity class as the
    # canary gap D-1 closes. conn.transaction() issues BEGIN on entry,
    # COMMIT on clean exit, ROLLBACK on exception (psycopg 3 explicit
    # transaction on an autocommit connection). One transaction across
    # ~2,500 upserts + history INSERTs + chunked UPDATEs is sub-minute on
    # Neon at v1 volume — no lock-duration concern. Boundaries per plan
    # D-2: finish_scraper_run stays OUTSIDE (the run row must land even
    # when Phase A rolls back; it executes after this function returns or
    # raises) and Phase B stays outside (its per-row fail-soft UPDATE
    # pattern wants autocommit per db.py:8-10).
    with conn.transaction():
        # UPSERT vendor_listings per-row with dynamic column list — preserves the
        # absent-column = keep-existing contract via per-row dynamic ON CONFLICT
        # DO UPDATE in _upsert_listing_row, by including only the row's actual
        # keys in both the INSERT column list and the ON CONFLICT DO UPDATE SET
        # clause. Per-row execute keeps the heterogeneous-column path clean
        # (CTK-025 match-field preservation rule + CTK-024 image_url-on-NEW-only
        # rule both ride on this); RETURNING id, product_url builds the
        # listing_id-by-url map inline (CTK-024 Session 5 — replaces the
        # post-upsert SELECT round-trip).
        if upserts:
            with conn.cursor() as cur:
                for row in upserts:
                    lid, purl = _upsert_listing_row(cur, row)
                    id_by_url[purl] = lid

        # Touch unchanged rows — UPDATE last_seen_at AND compare_at_price per
        # row. CTK-100 Wave-2 hotfix 2026-06-01: pre-fix this UPDATE wrote only
        # last_seen_at, so F6's UPSERT-path compare_at_price wiring at L275-287
        # was dark for every decision=='unchanged' row (the dominant steady-
        # state case). The UNNEST-into-data-table shape carries per-row
        # compare_at_price; psycopg adapts the Decimal-or-None mixed list to
        # numeric[] cleanly. Cast on the array side (%s::numeric[]) — without
        # the cast, psycopg emits a text[] which won't match the column type.
        # Single chunked UPDATE per 1000-row batch; chunk-size matches the
        # pre-fix shape (PostgREST URL-length workaround inheritance, no SQL
        # constraint).
        # CTK-124 F8: markdown_started_at joins the touch UPDATE as a three-
        # state CASE on the per-row markdown_action ('set' -> now, 'clear' ->
        # NULL, 'keep' -> existing value). One statement, one chunk loop —
        # the action discriminator rides a third UNNEST array (text[]) so the
        # keep case can preserve the column without a separate UPDATE shape
        # per action. Explicit ::timestamptz on the set-branch param keeps
        # CASE type inference off the text literal.
        if touch_payloads:
            with conn.cursor() as cur:
                for chunk in _chunks(touch_payloads, 1000):
                    ids = [p["id"] for p in chunk]
                    compare_ats = [p["compare_at_price"] for p in chunk]
                    md_actions = [p["markdown_action"] for p in chunk]
                    cur.execute(
                        "UPDATE vendor_listings AS vl "
                        "SET last_seen_at = %s, "
                        "    compare_at_price = data.compare_at_price, "
                        "    markdown_started_at = CASE data.markdown_action "
                        "      WHEN 'set' THEN %s::timestamptz "
                        "      WHEN 'clear' THEN NULL "
                        "      ELSE vl.markdown_started_at END "
                        "FROM (SELECT * FROM UNNEST(%s::bigint[], %s::numeric[], %s::text[])) "
                        "  AS data(id, compare_at_price, markdown_action) "
                        "WHERE vl.id = data.id",
                        (now, now, ids, compare_ats, md_actions),
                    )

        # CTK-094 cohort-OOS chunked UPDATE — flip in_stock=false ONLY on the
        # absent-set rows. Same chunked-ANY shape as touch_ids above. Direct
        # UPDATE (no UPSERT/ON CONFLICT) because the synthetic row would fail
        # NOT NULL on raw_title/normalized_title at the INSERT-side of an
        # UPSERT before ON CONFLICT could route to DO UPDATE — Postgres
        # evaluates NOT NULL before unique-conflict resolution. existing_id is
        # known from classify (URL was in existing_by_url with in_stock=True),
        # so the UPDATE-by-id path is both correct and cheaper than the UPSERT
        # round-trip.
        #
        # CTK-094 fold #3 (/code-review F3): last_seen_at deliberately NOT
        # touched. The column semantic is "last time we saw this URL in a
        # scrape"; cohort-OOS rows are absent FROM the scrape, so bumping
        # last_seen_at would falsify the staleness clock and break downstream
        # consumers — coral page 7d window (lib/queries/listings.ts), vendor +
        # deals 14d windows, rematch.py 7d backfill, named-corals
        # MAX(last_seen_at) surface, and the arch §2.2 stale-window mechanism
        # documented at poto.py:75 ("absent → no touch → goes stale → filtered
        # out"). The stale-window ages cohort-flipped rows out on its own
        # timeline; the in_stock=false flip is the cohort branch's only write.
        if cohort_oos_ids:
            with conn.cursor() as cur:
                for chunk in _chunks(cohort_oos_ids, 1000):
                    cur.execute(
                        "UPDATE vendor_listings SET in_stock = false "
                        "WHERE id = ANY(%s)",
                        (chunk,),
                    )

        # Hand listing_ids back to the mirror queue. (In-memory only; lives
        # inside the transaction block to preserve the pre-CTK-116 statement
        # order, not because it needs the boundary.)
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
        "Phase A complete: %d upserts + %d touches + %d cohort-oos + %d history rows; %d Phase B mirrors queued",
        len(upserts), len(touch_payloads), len(cohort_oos_ids), len(history), len(mirror_queue),
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
    "compare_at_price",  # CTK-100 Wave-2 F6 — flips the Wave-1 dark column on. Sits adjacent to current_price (semantic sibling). Both nullable numeric(10,2); _decimal_to_str returns None cleanly for None input.
    "markdown_started_at",  # CTK-124 F8 — episode-onset attestation (migration 0033). Present only on 'set' (now) / 'clear' (None) rows; omitted on 'keep' so the absent-column contract preserves the live onset.
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
