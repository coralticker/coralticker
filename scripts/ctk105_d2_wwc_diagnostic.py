"""CTK-105 D-2 — WWC diagnostic gate.

Three checks gating WWC's `cohort_oos_at_persist: true` opt-in per CTK-105
plan.md §Fix shape D-2:

  (i)  scraper_runs.listings_seen history for WWC, last 30 days. Step-down
       inflection points (= intake regression) vs. smooth-trend (= genuine
       catalog churn). Per-run (id, finished_at, status, listings_seen,
       html_hash[:12], git_sha[:8]) sorted by id desc.

  (ii) scraper_runs.html_hash history. Distinct hash values seen + the run
       transitions between them. A flip = vendor redesign / parser drift
       candidate (stale parser would mass-misintake on the new shape).

  (iii) Sample 20 random vendor_listings (vendor_id=2, in_stock=true,
        last_seen_at < last_success.finished_at - 5min). Polite-fetch the
        Shopify single-product JSON endpoint (<product_url>.json), paced by
        wwc.yaml request_delay_sec (2.0s). Classify each URL:

          - delisted        — 404 / 410 on .json endpoint
          - parser_filter_edge — 200 OK + product_type not in YAML allowlist
          - under_intake    — 200 OK + product_type in allowlist + at least
                              one variant.available=true (vendor lists it
                              live + buyable + our parser would accept it)
          - oos_at_vendor   — 200 OK + product_type in allowlist + no
                              variant.available=true (vendor lists but
                              sold out — folds with delisted for disposition)
          - error           — network / 5xx / non-JSON body / unexpected
                              shape; surfaced separately, NOT counted as live

Disposition rule:
  - >=3/20 sample classified `under_intake` (15%+ live-on-vendor + would-pass)
    -> HOLD WWC opt-in; surface to /lead-backend for sibling Tier-1A
    under-intake-fix CTK scaffold.
  - <=2/20 -> proceed to D-3 dry-run for WWC.

Write-zero. Read-only DB + polite-fetch only. Reads NEON_DATABASE_URL via
scrapers.common.db's load_dotenv side effect; reads wwc.yaml for
request_delay_sec + product_type_allowlist; uses scrapers.common.http
fetcher (standard-Chrome UA + retry policy from arch §2.4).
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

import yaml

from scrapers.common.db import get_conn
from scrapers.common.http import fetch

WWC_VENDOR_ID = 2
WWC_SLUG = "wwc"
SAMPLE_SIZE = 20
LIVE_DISPOSITION_THRESHOLD = 3  # >=3/20 under_intake -> HOLD opt-in
HISTORY_DAYS = 30
STALENESS_JITTER_MIN = 5  # tolerance against the pre-flight probe predicate
WWC_YAML_PATH = Path(__file__).parent.parent / "scrapers" / "vendors" / "wwc.yaml"
RNG_SEED = 42  # deterministic sample for reproducibility across reruns (/lead-backend disposition 2026-06-01)


def main() -> None:
    cfg = yaml.safe_load(WWC_YAML_PATH.read_text(encoding="utf-8")) or {}
    request_delay = float(cfg.get("request_delay_sec", 2.0))
    allowlist = set(cfg.get("category_filter", {}).get("product_type_allowlist", []))

    print("=" * 78)
    print(f"CTK-105 D-2 WWC diagnostic — vendor_id={WWC_VENDOR_ID} slug={WWC_SLUG}")
    print(f"request_delay_sec={request_delay}  allowlist={sorted(allowlist)}")
    print("=" * 78)

    with get_conn() as conn:
        _report_listings_seen_history(conn)
        _report_html_hash_history(conn)
        sample_rows, last_success_finished_at = _select_sample(conn)

    print()
    print("=" * 78)
    print(f"(iii) Live spot-check — sampling {len(sample_rows)} stale URLs")
    print(f"      stale predicate: in_stock=true AND last_seen_at < "
          f"{last_success_finished_at!s} - {STALENESS_JITTER_MIN}min")
    print(f"      polite-fetch: GET <product_url>.json, "
          f"request_delay_sec={request_delay}")
    print("=" * 78)

    # WWC cf shape passed to the shared classifier: product_type_allowlist
    # only (tag_denylist=[] per wwc.yaml). The shared classifier honors the
    # generalized (product_type_allowlist | tag_allowlist | tag_denylist)
    # shape so D-3's --classify mode can reuse it across the 7 sample-check
    # vendors with different filter shapes (RC uses tag_allowlist; others
    # use product_type_allowlist).
    cf = {"product_type_allowlist": list(allowlist), "tag_denylist": []}
    classifications: Counter[str] = Counter()
    rows_with_class: list[tuple[dict, str, str]] = []  # (row, klass, detail)
    for idx, row in enumerate(sample_rows, start=1):
        klass, detail = classify_url(row["product_url"], request_delay, cf)
        classifications[klass] += 1
        rows_with_class.append((row, klass, detail))
        print(f"  [{idx:>2}/{len(sample_rows)}] {klass:<20} "
              f"id={row['id']:>6} {row['product_url']}")
        print(f"           detail: {detail}")
        print(f"           title:  {row.get('raw_title', '')[:70]!r}")

    print()
    print("=" * 78)
    print("(iii) Classification roll-up")
    print("=" * 78)
    for klass in ("delisted", "oos_at_vendor", "parser_filter_edge", "under_intake", "error"):
        print(f"  {klass:<20} {classifications.get(klass, 0):>3} / {len(sample_rows)}")

    live = classifications.get("under_intake", 0)
    disposition = (
        f"HOLD WWC opt-in (>= {LIVE_DISPOSITION_THRESHOLD}/{SAMPLE_SIZE} under_intake "
        f"=> scaffold sibling under-intake-fix CTK)"
        if live >= LIVE_DISPOSITION_THRESHOLD
        else f"PROCEED to D-3 dry-run for WWC ({live}/{SAMPLE_SIZE} under_intake)"
    )
    print()
    print("=" * 78)
    print(f"DISPOSITION: {disposition}")
    print("=" * 78)

    if classifications.get("error", 0):
        print()
        print(f"NOTE: {classifications['error']} URL(s) bucketed as error — review per-URL "
              "detail above; do not count toward live disposition.")


def _report_listings_seen_history(conn) -> None:
    print()
    print("=" * 78)
    print(f"(i) scraper_runs.listings_seen history — last {HISTORY_DAYS} days")
    print("=" * 78)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, started_at, finished_at, status, listings_seen, "
            "html_hash, git_sha, error_class, error_message "
            "FROM scraper_runs "
            "WHERE vendor_id = %s "
            "  AND started_at >= NOW() - INTERVAL '%s days' "
            "ORDER BY id DESC",
            (WWC_VENDOR_ID, HISTORY_DAYS),
        )
        runs = cur.fetchall()
    print(f"  {len(runs)} runs in window")
    print()
    header = (f"  {'id':>5}  {'finished_at':<26}  {'status':<8}  "
              f"{'seen':>6}  {'hash[:12]':<12}  {'sha[:8]':<8}  err")
    print(header)
    print(f"  {'-'*5}  {'-'*26}  {'-'*8}  {'-'*6}  {'-'*12}  {'-'*8}  ---")
    for r in runs:
        finished = r["finished_at"].isoformat() if r["finished_at"] else "(none)"
        seen = r["listings_seen"] if r["listings_seen"] is not None else "-"
        hh = (r["html_hash"] or "")[:12] or "(none)"
        sha = (r["git_sha"] or "")[:8] or "(none)"
        err = r["error_class"] or ""
        print(f"  {r['id']:>5}  {finished:<26}  {r['status']:<8}  "
              f"{str(seen):>6}  {hh:<12}  {sha:<8}  {err}")


def _report_html_hash_history(conn) -> None:
    print()
    print("=" * 78)
    print(f"(ii) scraper_runs.html_hash transitions — last {HISTORY_DAYS} days")
    print("=" * 78)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, finished_at, status, html_hash "
            "FROM scraper_runs "
            "WHERE vendor_id = %s "
            "  AND started_at >= NOW() - INTERVAL '%s days' "
            "  AND status = 'success' "
            "  AND html_hash IS NOT NULL "
            "ORDER BY id ASC",
            (WWC_VENDOR_ID, HISTORY_DAYS),
        )
        rows = cur.fetchall()
    if not rows:
        print("  (no success runs with html_hash in window)")
        return
    distinct = []
    prev_hash = None
    for r in rows:
        if r["html_hash"] != prev_hash:
            distinct.append(r)
            prev_hash = r["html_hash"]
    print(f"  {len(rows)} success runs / {len(distinct)} distinct html_hash value(s)")
    print()
    print(f"  {'id':>5}  {'finished_at':<26}  {'hash[:24]':<24}  note")
    print(f"  {'-'*5}  {'-'*26}  {'-'*24}  ----")
    for i, r in enumerate(distinct):
        finished = r["finished_at"].isoformat() if r["finished_at"] else "(none)"
        hh = (r["html_hash"] or "")[:24]
        note = "FIRST" if i == 0 else "TRANSITION from previous distinct hash"
        print(f"  {r['id']:>5}  {finished:<26}  {hh:<24}  {note}")


def _select_sample(conn) -> tuple[list[dict], str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(finished_at) AS last_success "
            "FROM scraper_runs "
            "WHERE vendor_id = %s AND status = 'success' AND finished_at IS NOT NULL",
            (WWC_VENDOR_ID,),
        )
        last_success_row = cur.fetchone()
    last_success = last_success_row["last_success"]
    if last_success is None:
        print("ERROR: no successful WWC scraper run found; cannot define stale predicate.")
        sys.exit(2)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, product_url, raw_title, current_price, last_seen_at "
            "FROM vendor_listings "
            "WHERE vendor_id = %s "
            "  AND in_stock = true "
            "  AND last_seen_at < %s - INTERVAL '%s minutes' "
            "ORDER BY id",
            (WWC_VENDOR_ID, last_success, STALENESS_JITTER_MIN),
        )
        rows = cur.fetchall()

    print()
    print(f"(iii.pre) stale candidate pool: {len(rows)} rows "
          f"(pre-flight probe expected ~1,170; reconciliation within drift expected)")

    rng = random.Random(RNG_SEED)
    if len(rows) <= SAMPLE_SIZE:
        return rows, last_success.isoformat()
    return rng.sample(rows, SAMPLE_SIZE), last_success.isoformat()


def classify_url(product_url: str, request_delay: float, cf: dict) -> tuple[str, str]:
    """Classify a stale-in-DB URL by polite-fetching the Shopify single-
    product JSON endpoint and inspecting product_type + tags +
    variants.available against the vendor's YAML `category_filter` shape.

    Per Q-1 lean (DECIDED 2026-06-01): GET <product_url>.json (Shopify
    structured single-product endpoint) substitutes for the directive's
    HEAD shape. Same per-URL polite cost; exposes product_type for
    allowlist check, tags for denylist check, and variants[*].available
    for buyability — none of which HEAD can surface.

    cf is the vendor's YAML `category_filter` dict. Supported shapes:
      - product_type_allowlist: list[str]  (TSA / JF / BC / UC / Vivid / PE / WWC)
      - tag_allowlist: list[str]           (RC; matches parse_shopify L371)
      - tag_denylist: list[str]            (TSA / UC / Vivid / RC / PE; matches parse_shopify L375)

    Tag matching is case-insensitive to mirror parse_shopify L233/L371/L375.
    Shopify .json endpoint can return product.tags as a comma-separated
    STRING (single-product endpoint) or LIST (/products.json multi-product
    endpoint); handle both defensively. The parser at runtime sees the LIST
    shape, but the classifier here hits the single-product endpoint.

    Classes:
      - delisted          HTTP 404/410
      - parser_filter_edge 200 + product_type/tags rejected by YAML filter
      - oos_at_vendor     200 + would-pass filter + no variant available
      - under_intake      200 + would-pass filter + at least one variant
                          available (LIVE + BUYABLE + parser SHOULD have
                          intaken; the risk class for cohort-OOS opt-in)
      - error             network / non-200 / non-JSON / unexpected shape
    """
    json_url = product_url.rstrip("/") + ".json"
    result = fetch(json_url, request_delay_sec=request_delay)

    if result.status_code in (404, 410):
        return ("delisted", f"HTTP {result.status_code} on .json endpoint")
    if result.error_class is not None and result.body is None:
        return ("error", f"fetch error: error_class={result.error_class} "
                         f"http={result.status_code} msg={result.error_message!r}")
    if result.status_code != 200 or result.body is None:
        return ("error", f"unexpected: http={result.status_code} body_len="
                         f"{len(result.body) if result.body else 0}")

    try:
        data = json.loads(result.body)
    except Exception as exc:  # noqa: BLE001 — diagnostic, surface every shape
        return ("error", f"non-JSON body: {type(exc).__name__}: {exc}; "
                         f"body_head={result.body[:200]!r}")

    product = data.get("product")
    if not isinstance(product, dict):
        return ("error", f"missing product key; top-level keys={sorted(data.keys())}")

    product_type = product.get("product_type") or ""

    # Tags shape: list (multi-product endpoint) OR comma-separated string
    # (single-product endpoint). Defensive on both.
    tags_raw = product.get("tags", "")
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    else:
        tags = [str(t) for t in tags_raw]
    tags_lower = [t.lower() for t in tags]

    variants = product.get("variants") or []
    any_available = any(bool(v.get("available")) for v in variants)

    pt_allow = cf.get("product_type_allowlist")
    if pt_allow is not None:
        if product_type not in set(pt_allow):
            return ("parser_filter_edge",
                    f"product_type={product_type!r} not in allowlist; "
                    f"variants_available={any_available}")

    tag_allow = cf.get("tag_allowlist")
    if tag_allow is not None:
        tag_allow_lower = {t.lower() for t in tag_allow}
        if not any(t in tag_allow_lower for t in tags_lower):
            return ("parser_filter_edge",
                    f"no tag in tag_allowlist={tag_allow}; "
                    f"tags={tags[:5]}")

    tag_deny = cf.get("tag_denylist") or []
    if tag_deny:
        tag_deny_lower = {t.lower() for t in tag_deny}
        denied = [t for t in tags if t.lower() in tag_deny_lower]
        if denied:
            return ("parser_filter_edge",
                    f"tag denylist hit: {denied}; "
                    f"product_type={product_type!r}")

    if not any_available:
        return ("oos_at_vendor",
                f"product_type={product_type!r}; all variants unavailable")
    return ("under_intake",
            f"product_type={product_type!r}; variants_available=True "
            f"(live + buyable + would-pass)")


if __name__ == "__main__":
    main()
