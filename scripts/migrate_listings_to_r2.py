"""scripts/migrate_listings_to_r2.py — CTK-036 cut-3 (revised 2026-05-15).

Get image bytes to R2 + point vendor_listings.image_url at the new bucket
WITHOUT going through any Supabase project API (PostgREST + Storage are
project-quota-restricted; Management API is exempt).

Path:
  1. Read vendors row + run /products.json fresh via parse_shopify.fetch_and_parse
     → list of items with product_url + vendor_image_url
  2. For each item: images.mirror(slug, product_url, vendor_image_url) — fetch
     from vendor CDN, compress, PUT to R2 via boto3 (cut-2 forward-write code)
  3. Batched UPDATE vendor_listings.image_url via `supabase db query --linked`
     subprocess (Management API is exempt from project quota restriction)

No supabase-py REST calls. No Supabase Storage reads. Only Management API
(via CLI subprocess) + boto3 + vendor CDN.

Invocation:
  python -m scripts.migrate_listings_to_r2 --vendor pacific_east [--dry-run] [--limit N] [--workers N]

Per-vendor sequencing PE → WWC → TSA (JF excluded per Q-CUT3-C).

Resumability: progress written to .migrate-r2-progress-{slug}.json after every
successful PUT. Re-running picks up where it left off (idempotent — R2 PUT is
last-write-wins on the same key).

CTK-036 cleanup: delete this script post-cut-7 dead-bucket state.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scrapers.common import images, parse_shopify
# scrapers.common.db imports python-dotenv at module-load and fires
# load_dotenv() — needed so R2_* env vars from .env reach images.py.
from scrapers.common import db  # noqa: F401 — side-effect import for .env load

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


_VENDOR_SLUGS = ("pacific_east", "wwc", "tsa", "jf")  # JF re-included per Jon 2026-05-15 (Q-CUT3-C overridden)
_FAIL_RATE_CEILING_PCT = 5.0


# ─── Filesystem helpers ───────────────────────────────────────────────────────
def _progress_path(vendor_slug: str) -> Path:
    return Path(f".migrate-r2-progress-{vendor_slug}.json")


_progress_lock = threading.Lock()


def _atomic_write_json(path: Path, data: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_progress(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("progress file %s corrupt; treating as empty", path)
        return []


# ─── Management API helpers (subprocess `supabase db query --linked`) ─────────
def supabase_query(sql: str) -> list[dict]:
    """Run SQL via supabase CLI Management API. Bypasses project-level quota
    restriction that blocks PostgREST + Storage endpoints. Returns rows
    list (empty for non-SELECT). Raises RuntimeError on CLI failure."""
    r = subprocess.run(
        ["supabase", "db", "query", "--linked", sql],
        capture_output=True, text=True, encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError(f"supabase CLI failed (exit {r.returncode}): {r.stderr.strip()[:500]}")
    # CLI output: JSON object with "rows" key; UPDATEs return empty rows
    try:
        out = json.loads(r.stdout)
        return out.get("rows", [])
    except json.JSONDecodeError:
        # UPDATE/DELETE may emit non-JSON status text on success; treat as empty
        return []


def supabase_query_file(sql_text: str) -> None:
    """Run SQL via supabase CLI Management API using --file. Used for batch
    updates that exceed Windows command-line length limit (~8 KB cap on
    cmd.exe arg). Single CLI invocation per call — sidesteps both the arg-
    length wall AND the temp-role provisioning contention that fired on
    parallel batched calls 2026-05-15 (WWC re-run SASL auth FATAL after
    ~5 of 41 chunks)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as tf:
        tf.write(sql_text)
        tmppath = tf.name
    try:
        r = subprocess.run(
            ["supabase", "db", "query", "--linked", "--file", tmppath],
            capture_output=True, text=True, encoding="utf-8",
        )
        if r.returncode != 0:
            raise RuntimeError(f"supabase CLI failed (exit {r.returncode}): {r.stderr.strip()[:500]}")
    finally:
        try:
            os.unlink(tmppath)
        except OSError:
            pass


def fetch_vendor_row(slug: str) -> dict:
    """Read vendors row via Management API."""
    rows = supabase_query(
        f"SELECT id, slug, base_url, image_strategy "
        f"FROM vendors WHERE slug = '{slug}'"
    )
    if not rows:
        raise RuntimeError(f"vendors row not found for slug={slug}")
    return rows[0]


def load_yaml_config(slug: str) -> dict:
    """Per-vendor YAML at scrapers/vendors/<slug>.yaml."""
    yaml_path = Path(__file__).parent.parent / "scrapers" / "vendors" / f"{slug}.yaml"
    if not yaml_path.exists():
        log.warning("no YAML at %s — using vendors-row defaults", yaml_path)
        return {}
    return yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}


# ─── Per-item worker (thread-safe via threading.local in images._S3_CLIENT) ──
@dataclass
class TransferResult:
    product_url: str
    vendor_image_url: str
    r2_url: str | None
    succeeded: bool
    error: str | None = None


def _transfer_one(slug: str, item: dict) -> TransferResult:
    """Worker function: call images.mirror() for this item. mirror() handles
    the full vendor-fetch → compress → R2 PUT round-trip."""
    product_url = item["product_url"]
    vendor_image_url = item.get("vendor_image_url")
    if not vendor_image_url:
        return TransferResult(product_url, "", None, False, "no vendor_image_url in parsed item")
    try:
        r2_url = images.mirror(slug, product_url, vendor_image_url)
    except Exception as e:  # noqa: BLE001 — fail-soft per arch decision #55
        return TransferResult(product_url, vendor_image_url, None, False, f"mirror exception: {e}")
    if r2_url is None:
        return TransferResult(product_url, vendor_image_url, None, False, "mirror returned None")
    return TransferResult(product_url, vendor_image_url, r2_url, True)


# ─── Bulk UPDATE batching ─────────────────────────────────────────────────────
def _sql_quote(s: str) -> str:
    """Single-quote escaping for SQL literal."""
    return "'" + s.replace("'", "''") + "'"


def batch_update_image_urls(vendor_id: int, mappings: list[tuple[str, str]]) -> int:
    """Bulk UPDATE vendor_listings.image_url via Management API. Writes ALL
    UPDATE statements to a tempfile + invokes `supabase db query --linked
    --file <tempfile>` once per vendor.

    Single-statement-per-row form (vs. the earlier CASE-WHEN batching) —
    simpler SQL, no shell-arg-length concern (file is read by the CLI, not
    passed as arg), no temp-role rate-limit (one CLI invocation = one temp
    role provisioned).

    Earlier chunk_size=200 tripped WinError 206 (Windows cmd.exe ~8 KB
    arg cap); chunk_size=30 worked but 41 sequential calls × ~10s
    CLI-overhead-per-call hit a SASL auth wall on the temp-role
    provisioning (WWC re-run 2026-05-15).

    Returns row count requested for UPDATE (best-effort; CLI doesn't
    surface affected-row counts via this path)."""
    if not mappings:
        return 0
    log.info("batch UPDATE: %d mappings in single tempfile call", len(mappings))
    sql_lines = [
        f"UPDATE vendor_listings SET image_url = {_sql_quote(r)} "
        f"WHERE vendor_id = {vendor_id} AND product_url = {_sql_quote(p)};"
        for p, r in mappings
    ]
    sql_text = "\n".join(sql_lines) + "\n"
    supabase_query_file(sql_text)
    log.info("  UPDATE complete (%d statements)", len(mappings))
    return len(mappings)


# ─── Per-vendor orchestrator ──────────────────────────────────────────────────
@dataclass
class VendorResult:
    vendor_slug: str
    items_parsed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_resumed: int = 0
    bytes_transferred: int = 0
    duration_seconds: float = 0.0
    rows_updated: int = 0
    failure_examples: list[str] = field(default_factory=list)

    @property
    def attempted(self) -> int:
        return self.succeeded + self.failed

    @property
    def fail_rate_pct(self) -> float:
        return (self.failed / self.attempted * 100.0) if self.attempted else 0.0


def run_vendor(slug: str, workers: int, dry_run: bool, limit: int | None) -> VendorResult:
    started_at = time.monotonic()
    log.info("migrate starting for vendor=%s%s", slug, " [DRY-RUN]" if dry_run else "")

    vendor_row = fetch_vendor_row(slug)
    yaml_config = load_yaml_config(slug)
    config = {**vendor_row, **yaml_config}
    log.info("config: vendor_id=%d base_url=%s", vendor_row["id"], vendor_row["base_url"])

    # Stage A — parse /products.json fresh (bypasses Supabase entirely)
    log.info("fetching + parsing /products.json...")
    parsed = parse_shopify.fetch_and_parse(config)
    log.info("parsed %d items, html_hash=%s last_status=%s",
             len(parsed.items), parsed.html_hash, parsed.http_status_last)

    # Resume support — skip product_urls already in progress file
    progress_path = _progress_path(slug)
    progress = _load_progress(progress_path)
    processed_urls = {entry["product_url"] for entry in progress}

    work_items = [it for it in parsed.items
                  if it.get("vendor_image_url") and it["product_url"] not in processed_urls]

    result = VendorResult(
        vendor_slug=slug,
        items_parsed=len(parsed.items),
        skipped_resumed=len(processed_urls),
    )

    if limit is not None:
        work_items = work_items[:limit]
        log.info("--limit %d applied; will attempt %d items", limit, len(work_items))
    log.info("phase 1: %d items to mirror after resume-skip", len(work_items))

    if dry_run:
        for it in work_items[:5]:
            log.info("  [dry-run] would mirror: %s ← %s", it["product_url"], it["vendor_image_url"])
        if len(work_items) > 5:
            log.info("  ... +%d more", len(work_items) - 5)
        result.duration_seconds = time.monotonic() - started_at
        return result

    # Stage B — parallel transfer
    succeed_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_transfer_one, slug, it): it for it in work_items}
        for fut in as_completed(futures):
            tr = fut.result()
            if tr.succeeded:
                with succeed_lock:
                    result.succeeded += 1
                    progress.append({
                        "product_url": tr.product_url,
                        "vendor_image_url": tr.vendor_image_url,
                        "r2_url": tr.r2_url,
                        "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    })
                    with _progress_lock:
                        _atomic_write_json(progress_path, progress)
            else:
                result.failed += 1
                if len(result.failure_examples) < 10:
                    result.failure_examples.append(f"{tr.product_url}: {tr.error}")
                log.warning("transfer failed: %s — %s", tr.product_url, tr.error)

    # Stage C — bulk UPDATE vendor_listings.image_url via Management API
    mappings = [(e["product_url"], e["r2_url"]) for e in progress]
    log.info("stage C: bulk UPDATE for %d (product_url → r2_url) mappings", len(mappings))
    result.rows_updated = batch_update_image_urls(vendor_row["id"], mappings)
    result.duration_seconds = time.monotonic() - started_at
    return result


# ─── Summary ──────────────────────────────────────────────────────────────────
def print_summary(result: VendorResult, dry_run: bool, workers: int) -> None:
    print()
    print("=" * 78)
    print(f"migrate summary -- vendor={result.vendor_slug}{' [DRY-RUN]' if dry_run else ''}")
    print("=" * 78)
    print(f"  items parsed:           {result.items_parsed}")
    print(f"  resumed (skipped):      {result.skipped_resumed}")
    print(f"  succeeded:              {result.succeeded}")
    print(f"  failed:                 {result.failed}")
    print(f"  duration:               {result.duration_seconds:.1f}s")
    if result.duration_seconds > 0 and result.succeeded > 0:
        throughput = result.succeeded / result.duration_seconds
        worker_util = throughput / workers
        print(f"  throughput:             {throughput:.2f} obj/sec across {workers} workers ({worker_util:.2f} obj/sec/worker)")
    print(f"  failure rate:           {result.fail_rate_pct:.2f}%")
    if not dry_run:
        print(f"  rows updated:           {result.rows_updated}")
    if result.failure_examples:
        print("  failure examples:")
        for ex in result.failure_examples:
            print(f"    {ex}")
    print()


# ─── CLI entry ────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CTK-036 cut-3 revised: migrate listings to R2 via vendor re-fetch + Management API"
    )
    parser.add_argument("--vendor", required=True, choices=_VENDOR_SLUGS,
                        help="Vendor slug (JF excluded per Q-CUT3-C)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip mirror + UPDATE; log what would happen")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N successful transfers (smoke gate)")
    parser.add_argument("--workers", type=int, default=6,
                        help="Worker count (default 6)")
    args = parser.parse_args(argv)

    if args.workers < 1 or args.workers > 16:
        log.error("--workers out of bounds (1-16); got %d", args.workers)
        return 1

    try:
        result = run_vendor(args.vendor, args.workers, args.dry_run, args.limit)
    except RuntimeError as e:
        log.error("vendor run failed: %s", e)
        return 1
    except Exception as e:  # noqa: BLE001 — surface unexpected types loudly
        log.exception("unexpected error: %s", e)
        return 1

    print_summary(result, dry_run=args.dry_run, workers=args.workers)

    if args.dry_run:
        return 0
    if result.fail_rate_pct > _FAIL_RATE_CEILING_PCT:
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
