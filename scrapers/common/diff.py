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

from scrapers.common import images as image_pipeline

log = logging.getLogger(__name__)


Decision = Literal["new", "price_changed", "restocked", "oos", "unchanged"]


@dataclass
class ItemDecision:
    item: dict
    decision: Decision
    existing_id: int | None = None  # set on update paths; None for "new"


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


def persist(client, vendor_row: dict, decisions: list[ItemDecision], run_id: int) -> None:
    """Stage 6 — UPSERT vendor_listings; INSERT price_history on (price, stock)
    change; mirror images per CTK-019 #55 inline. Per arch §3.2 + CTK-023 Call 2:
    NO matcher call between stage 5 and stage 6 in CTK-024 — Pacific East ships
    matcher-naive. Retro-fit when CTK-025 lands the inline scaffold."""
    vendor_id = vendor_row["id"]
    vendor_slug = vendor_row["slug"]
    base_url = vendor_row["base_url"].rstrip("/")
    image_strategy = vendor_row.get("image_strategy", "mirror")

    now = datetime.now(timezone.utc).isoformat()

    upserts: list[dict] = []
    history: list[dict] = []
    touch_ids: list[int] = []

    for d in decisions:
        item = d.item
        absolute_url = base_url + item["product_url"] if item["product_url"].startswith("/") else item["product_url"]

        if d.decision == "unchanged":
            touch_ids.append(d.existing_id)  # type: ignore[arg-type]
            continue

        # Image-pipeline integration per CTK-019 #55 — synchronous, 1-attempt.
        # Mirror only fires on NEW listings (avoids re-fetching the same image
        # every scrape for an unchanged listing). On hotlink strategy, store
        # the vendor URL verbatim. On mirror failure, image_url stays NULL.
        image_url: str | None = None
        if d.decision == "new" and item.get("vendor_image_url"):
            if image_strategy == "hotlink":
                image_url = item["vendor_image_url"]
            else:  # mirror (default per #52)
                image_url = image_pipeline.mirror(client, vendor_slug, item["product_url"], item["vendor_image_url"])

        row = {
            "vendor_id": vendor_id,
            "vendor_sku": item.get("vendor_sku"),
            "product_url": absolute_url,
            "raw_title": item["raw_title"],
            "normalized_title": item["normalized_title"],
            "current_price": _decimal_to_str(item.get("current_price")),
            "currency": item.get("currency", "USD"),
            "in_stock": item["in_stock"],
            "category": item.get("category"),
            "lineage_flag": item.get("lineage_flag", "unknown"),
            "last_seen_at": now,
        }
        if d.decision == "new":
            row["first_seen_at"] = now
            if image_url is not None:
                row["image_url"] = image_url
        if d.decision == "price_changed":
            row["last_price_changed_at"] = now

        upserts.append(row)

        # price_history INSERT on (price, stock) change OR on new — captures the
        # baseline observation per arch §1.5 write rule.
        if d.decision in ("new", "price_changed", "restocked", "oos"):
            history.append({
                "price": _decimal_to_str(item.get("current_price")),
                "in_stock": item["in_stock"],
                "scraper_run_id": run_id,
                # listing_id resolved post-upsert (see _link_history below)
                "_product_url": absolute_url,  # join key; stripped before INSERT
            })

    # UPSERT vendor_listings in chunks. PostgREST upsert with on_conflict
    # respects the UNIQUE (vendor_id, product_url) index per arch §1.4.
    if upserts:
        for chunk in _chunks(upserts, 500):
            client.table("vendor_listings").upsert(chunk, on_conflict="vendor_id,product_url").execute()

    # Touch unchanged rows (last_seen_at only). Cheap targeted UPDATEs.
    # Batched into one UPDATE WHERE id IN (...) chunks per round-trip.
    if touch_ids:
        for chunk in _chunks(touch_ids, 500):
            client.table("vendor_listings").update({"last_seen_at": now}).in_("id", chunk).execute()

    # Resolve listing_id for the history rows — fetch ids by product_url.
    if history:
        urls = list({h["_product_url"] for h in history})
        rows = []
        for chunk in _chunks(urls, 500):
            rows.extend(
                client.table("vendor_listings")
                .select("id,product_url")
                .eq("vendor_id", vendor_id)
                .in_("product_url", chunk)
                .execute()
                .data
                or []
            )
        id_by_url = {r["product_url"]: r["id"] for r in rows}
        history_rows = []
        for h in history:
            lid = id_by_url.get(h["_product_url"])
            if lid is None:
                log.warning("price_history: no listing_id for %s — skip", h["_product_url"])
                continue
            history_rows.append({
                "listing_id": lid,
                "price": h["price"],
                "in_stock": h["in_stock"],
                "scraper_run_id": h["scraper_run_id"],
            })
        if history_rows:
            for chunk in _chunks(history_rows, 500):
                client.table("price_history").insert(chunk).execute()


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
