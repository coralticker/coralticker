"""scripts/backfill_image_compression.py — CTK-035 Session 2 bulk-pass
backfill of existing listing-images bucket objects through the Pillow WebP
compression pipeline shipped in Session 1 (commit 7b16271).

Three-phase script, one-vendor-at-a-time per CTK-035 plan.md D-4
(PE → WWC → TSA):

    Phase 1   per-object download → _compress() → upload .webp + progress
              capture (resumable via .backfill-progress-{slug}.json)
    Phase 2   image_url SQL UPDATE rewrite — printed to stdout, Jon runs
              via `supabase db query --linked` (single-statement UPDATE on
              ~5k rows beats 5k REST calls)
    Phase 3   bulk-delete pre-rewrite paths in batches of 100 — gated by
              integrity check that Phase 2 ran (vendor_listings .webp row
              count == storage.objects .webp count under {slug}/)

Invocation:

    python -m scripts.backfill_image_compression --vendor <slug> --phase 1 [--dry-run] [--limit N]
    python -m scripts.backfill_image_compression --vendor <slug> --phase 3

Vendor slugs ∈ {pacific_east, wwc, tsa}; argparse rejects anything else.

═════ Per-vendor runbook ═════════════════════════════════════════════════════

Per CTK-035 plan.md D-1 + D-4, one vendor at a time, PE → WWC → TSA.
Per-vendor wallclock budget: ~3 hours (plan.md acceptance line 103).

1. Disable cron for the vendor (Jon-side):
       supabase db query --linked "UPDATE vendors SET active=false WHERE slug='<slug>'"

2. (Optional) Smoke-run on first 50 objects to sanity-check before the full pass:
       python -m scripts.backfill_image_compression --vendor <slug> --phase 1 --dry-run --limit 50

3. Run Phase 1 (compression + re-upload + progress capture):
       python -m scripts.backfill_image_compression --vendor <slug> --phase 1

4. Run the Phase 2 SQL printed at the end of Phase 1 stdout via:
       supabase db query --linked "<SQL printed by Phase 1>"

5. Run Phase 3 (bulk-delete pre-rewrite paths; aborts if integrity check fails):
       python -m scripts.backfill_image_compression --vendor <slug> --phase 3

6. 8-image visual-quality spot-check per plan.md acceptance line 105.
       - ≤2 of 8 visibly soft/banded → q80 holds, proceed.
       - ≥3 of 8 → bail to q85 (patch _WEBP_QUALITY in scrapers/common/images.py,
         delete .backfill-progress-{slug}.json + .backfill-pre-rewrite-paths-{slug}.json,
         re-run from step 3).

7. Re-enable cron for the vendor (Jon-side):
       supabase db query --linked "UPDATE vendors SET active=true WHERE slug='<slug>'"

8. Advance to next vendor in PE → WWC → TSA sequence.

Resumability: Phase 1 writes .backfill-progress-{slug}.json after every
successful upload (atomic write-temp-then-rename). Re-running Phase 1 after
Ctrl-C / crash skips already-processed paths. Phase 3 reads
.backfill-pre-rewrite-paths-{slug}.json (written at end of Phase 1) — if
that file is missing Phase 3 refuses to run.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scrapers.common import db, images

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


_BUCKET = images._BUCKET  # 'listing-images'
_VENDOR_SLUGS = ("pacific_east", "wwc", "tsa")
_LIST_PAGE_SIZE = 100
_DELETE_BATCH_SIZE = 100
_WEBP_EXT = ".webp"
_FAIL_RATE_CEILING_PCT = 5.0  # plan.md acceptance line 104


# ─── Filesystem helpers ───────────────────────────────────────────────────────
def _progress_path(vendor_slug: str) -> Path:
    return Path(f".backfill-progress-{vendor_slug}.json")


def _pre_rewrite_paths_path(vendor_slug: str) -> Path:
    return Path(f".backfill-pre-rewrite-paths-{vendor_slug}.json")


def _meta_path(vendor_slug: str) -> Path:
    return Path(f".backfill-meta-{vendor_slug}.json")


def _atomic_write_json(path: Path, data: object) -> None:
    """Write-temp-then-rename so Ctrl-C mid-write doesn't corrupt the file."""
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


# ─── Storage SDK helpers ──────────────────────────────────────────────────────
def _list_all_objects(client, vendor_slug: str) -> list[dict]:
    """Paginate storage.list() until exhausted; build full list in memory.

    Per CTK-034 .range()/.order() precedent — paginated APIs that don't
    guarantee stable ordering across calls must NOT be iterated live.
    Building the list in one pass first means a mid-stream insert (fresh
    cron mirror) can't shift the iteration window.
    """
    objects: list[dict] = []
    offset = 0
    while True:
        page = client.storage.from_(_BUCKET).list(
            path=vendor_slug,
            options={"limit": _LIST_PAGE_SIZE, "offset": offset},
        )
        if not page:
            break
        objects.extend(page)
        if len(page) < _LIST_PAGE_SIZE:
            break
        offset += _LIST_PAGE_SIZE
    return objects


def _bucket_path(vendor_slug: str, name: str) -> str:
    """Bucket key for an object listed under {vendor_slug}/. Storage SDK's
    .list(path=vendor_slug) returns names relative to that folder; download
    + upload + remove paths take the absolute bucket key."""
    return f"{vendor_slug}/{name}"


def _new_path_from_old(old_full_path: str) -> str:
    """{vendor_slug}/{handle}.{old_ext} → {vendor_slug}/{handle}.webp."""
    base, _ext = os.path.splitext(old_full_path)
    return base + _WEBP_EXT


# ─── Stat helpers ─────────────────────────────────────────────────────────────
def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    n = len(values)
    idx = max(0, min(n - 1, int(round(pct / 100.0 * (n - 1)))))
    return sorted(values)[idx]


# ─── Phase 1 ──────────────────────────────────────────────────────────────────
@dataclass
class Phase1Result:
    total_discovered: int = 0
    succeeded: int = 0
    pillow_failure_count: int = 0
    skipped_already_webp: int = 0
    skipped_resumed: int = 0
    bytes_old_succeeded: list[int] = field(default_factory=list)
    bytes_new_succeeded: list[int] = field(default_factory=list)

    @property
    def attempted(self) -> int:
        return self.succeeded + self.pillow_failure_count

    @property
    def fail_rate_pct(self) -> float:
        return (self.pillow_failure_count / self.attempted * 100.0) if self.attempted else 0.0

    @property
    def bytes_reclaimed(self) -> int:
        return sum(self.bytes_old_succeeded) - sum(self.bytes_new_succeeded)


def run_phase1(
    client,
    vendor: dict,
    dry_run: bool = False,
    limit: int | None = None,
) -> Phase1Result:
    """Per-object loop: download → compress → upload → progress capture.

    Pillow exception per object → log + skip + continue per CTK-035 D-3
    (fail-soft semantics, arch decision #55). Failure rate >5% surfaces as
    a stdout WARN at summary time — operator escalates per plan.md
    acceptance line 104 before next vendor.
    """
    vendor_slug = vendor["slug"]
    progress_path = _progress_path(vendor_slug)
    progress = _load_progress(progress_path)
    processed_old_names = {entry["old_name"] for entry in progress}

    if not dry_run and not _meta_path(vendor_slug).exists():
        _atomic_write_json(
            _meta_path(vendor_slug),
            {"phase1_started_at": datetime.now(timezone.utc).isoformat()},
        )

    log.info(
        "phase 1 starting for vendor=%s%s; %d objects already in progress file",
        vendor_slug, " [DRY-RUN]" if dry_run else "", len(progress),
    )

    objects = _list_all_objects(client, vendor_slug)
    result = Phase1Result(total_discovered=len(objects))
    log.info("listed %d objects in %s/", result.total_discovered, vendor_slug)

    for obj in objects:
        if limit is not None and result.succeeded >= limit:
            log.info("--limit %d reached; stopping after %d successes",
                     limit, result.succeeded)
            break

        name = obj["name"]
        old_full = _bucket_path(vendor_slug, name)

        if old_full in processed_old_names:
            result.skipped_resumed += 1
            continue

        if name.lower().endswith(_WEBP_EXT):
            result.skipped_already_webp += 1
            continue

        try:
            body_old = client.storage.from_(_BUCKET).download(old_full)
        except Exception as e:  # noqa: BLE001 — Storage SDK exceptions heterogeneous
            log.info("download failed for %s: %s", old_full, e)
            result.pillow_failure_count += 1
            continue

        try:
            body_new = images._compress(body_old)
        except Exception as e:  # noqa: BLE001 — Pillow decode exceptions heterogeneous
            log.info("compression failed for %s: %s", old_full, e)
            result.pillow_failure_count += 1
            continue

        new_full = _new_path_from_old(old_full)

        if dry_run:
            log.info(
                "[dry-run] %s: %d bytes old -> %d bytes new (would upload to %s)",
                old_full, len(body_old), len(body_new), new_full,
            )
            result.succeeded += 1
            result.bytes_old_succeeded.append(len(body_old))
            result.bytes_new_succeeded.append(len(body_new))
            continue

        try:
            client.storage.from_(_BUCKET).upload(
                path=new_full,
                file=body_new,
                file_options={"content-type": "image/webp", "upsert": "true"},
            )
        except Exception as e:  # noqa: BLE001
            log.info("upload failed for %s: %s", new_full, e)
            result.pillow_failure_count += 1
            continue

        result.succeeded += 1
        result.bytes_old_succeeded.append(len(body_old))
        result.bytes_new_succeeded.append(len(body_new))
        progress.append({
            "old_name": old_full,
            "new_name": new_full,
            "bytes_old": len(body_old),
            "bytes_new": len(body_new),
        })
        _atomic_write_json(progress_path, progress)

    if not dry_run and progress:
        _atomic_write_json(
            _pre_rewrite_paths_path(vendor_slug),
            [entry["old_name"] for entry in progress],
        )

    return result


def print_phase1_summary(result: Phase1Result, vendor_slug: str, dry_run: bool) -> None:
    print()
    print("=" * 78)
    print(f"Phase 1 summary -- vendor={vendor_slug}{' [DRY-RUN]' if dry_run else ''}")
    print("=" * 78)
    print(f"  objects discovered:       {result.total_discovered}")
    print(f"  already-.webp skipped:    {result.skipped_already_webp}")
    print(f"  resumed (in progress):    {result.skipped_resumed}")
    print(f"  succeeded:                {result.succeeded}")
    print(f"  pillow/io failures:       {result.pillow_failure_count}")
    if result.bytes_old_succeeded:
        print(
            f"  bytes_old p50/p90/p99/max: "
            f"{_percentile(result.bytes_old_succeeded, 50):,} / "
            f"{_percentile(result.bytes_old_succeeded, 90):,} / "
            f"{_percentile(result.bytes_old_succeeded, 99):,} / "
            f"{max(result.bytes_old_succeeded):,}"
        )
        print(
            f"  bytes_new p50/p90/p99/max: "
            f"{_percentile(result.bytes_new_succeeded, 50):,} / "
            f"{_percentile(result.bytes_new_succeeded, 90):,} / "
            f"{_percentile(result.bytes_new_succeeded, 99):,} / "
            f"{max(result.bytes_new_succeeded):,}"
        )
        print(f"  bytes reclaimed:          {result.bytes_reclaimed:,}")
    print(f"  failure rate:             {result.fail_rate_pct:.2f}%")
    print()

    if result.fail_rate_pct > _FAIL_RATE_CEILING_PCT:
        print(
            f"  WARN: failure rate {result.fail_rate_pct:.2f}% exceeds "
            f"{_FAIL_RATE_CEILING_PCT:.0f}% acceptance threshold "
            f"(plan.md acceptance line 104) -- escalate to /lead-backend "
            f"before next vendor begins."
        )
        print()

    if dry_run:
        print("Dry-run complete -- no objects modified, no progress file written.")
        print()
        return

    print("--- Phase 2 -- run via `supabase db query --linked` ---")
    print(
        f"UPDATE vendor_listings\n"
        f"SET image_url = regexp_replace(image_url, '\\.(jpg|jpeg|png|gif)$', '.webp')\n"
        f"WHERE vendor_id = (SELECT id FROM vendors WHERE slug = '{vendor_slug}')\n"
        f"  AND image_url IS NOT NULL\n"
        f"  AND image_url ~ '\\.(jpg|jpeg|png|gif)$';"
    )
    print()
    print(f"After Phase 2 SQL completes, run:")
    print(f"  python -m scripts.backfill_image_compression --vendor {vendor_slug} --phase 3")
    print()
    print(
        f"Reminder: 8-image visual-quality spot-check per plan.md acceptance "
        f"line 105 BEFORE re-enabling cron + advancing to next vendor."
    )
    print()


# ─── Phase 3 ──────────────────────────────────────────────────────────────────
@dataclass
class Phase3Result:
    deleted: int = 0
    bytes_reclaimed: int = 0
    rows_webp: int = 0
    bucket_webp: int = 0
    integrity_passed: bool = False


def run_phase3(client, vendor: dict) -> Phase3Result | None:
    """Bulk-delete pre-rewrite paths captured during Phase 1.

    Refuses (returns None) if the pre-rewrite paths file is missing OR if
    the per-vendor integrity check fails (vendor_listings.image_url ending
    in '.webp' count != storage.objects bucket count for {slug}/*.webp).
    Plan.md acceptance line 102 — gate, not just post-condition. Caller
    converts None to a non-zero exit code.
    """
    vendor_slug = vendor["slug"]
    vendor_id = vendor["id"]
    pre_rewrite_path = _pre_rewrite_paths_path(vendor_slug)

    if not pre_rewrite_path.exists():
        log.error(
            "Phase 3 prerequisite missing: %s. Run Phase 1 first.",
            pre_rewrite_path,
        )
        return None

    pre_rewrite_paths: list[str] = json.loads(pre_rewrite_path.read_text(encoding="utf-8"))

    rows_webp = (
        client.table("vendor_listings")
        .select("id", count="exact")
        .eq("vendor_id", vendor_id)
        .like("image_url", "%.webp")
        .execute()
        .count
    )
    objects = _list_all_objects(client, vendor_slug)
    bucket_webp = sum(1 for o in objects if o["name"].lower().endswith(_WEBP_EXT))

    result = Phase3Result(
        rows_webp=rows_webp,
        bucket_webp=bucket_webp,
        integrity_passed=(rows_webp == bucket_webp),
    )

    if not result.integrity_passed:
        log.error(
            "Phase 2 SQL did not complete successfully -- image_url/.webp count "
            "mismatch: vendor_listings rows=%d, storage.objects=%d. "
            "Re-run Phase 2 SQL via `supabase db query --linked` and re-verify.",
            rows_webp, bucket_webp,
        )
        return result

    log.info(
        "Phase 2 integrity check passed: vendor_listings.image_url '.webp' = %d "
        "matches storage.objects '%s/%%.webp' = %d. Proceeding to bulk-delete.",
        rows_webp, vendor_slug, bucket_webp,
    )

    total = len(pre_rewrite_paths)
    for i in range(0, total, _DELETE_BATCH_SIZE):
        batch = pre_rewrite_paths[i:i + _DELETE_BATCH_SIZE]
        client.storage.from_(_BUCKET).remove(batch)
        result.deleted += len(batch)
        log.info("deleted batch %d-%d / %d", i, i + len(batch), total)

    progress = _load_progress(_progress_path(vendor_slug))
    result.bytes_reclaimed = sum(
        entry.get("bytes_old", 0) - entry.get("bytes_new", 0) for entry in progress
    )

    return result


def print_phase3_summary(result: Phase3Result, vendor_slug: str) -> None:
    print()
    print("=" * 78)
    print(f"Phase 3 summary -- vendor={vendor_slug}")
    print("=" * 78)
    if not result.integrity_passed:
        print(
            f"  ABORTED: integrity check failed "
            f"(vendor_listings .webp rows={result.rows_webp}, "
            f"storage.objects .webp={result.bucket_webp})."
        )
        print(f"  No objects deleted.")
        print()
        return

    # Wallclock from meta file if present.
    meta = _meta_path(vendor_slug)
    wallclock_str = "unknown (Phase 1 meta file missing)"
    if meta.exists():
        try:
            started_at = datetime.fromisoformat(
                json.loads(meta.read_text(encoding="utf-8"))["phase1_started_at"]
            )
            elapsed = datetime.now(timezone.utc) - started_at
            wallclock_str = f"{elapsed}"
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

    print(f"  pre-rewrite paths deleted:    {result.deleted}")
    print(f"  bytes reclaimed (Phase 1):    {result.bytes_reclaimed:,}")
    print(f"  Phase 1 -> Phase 3 wallclock: {wallclock_str}")
    print()

    next_vendor_idx = _VENDOR_SLUGS.index(vendor_slug) + 1
    print(
        f"Next: 8-image visual-quality spot-check per plan.md acceptance line 105, "
        f"then re-enable cron:"
    )
    print(
        f"  supabase db query --linked "
        f"\"UPDATE vendors SET active=true WHERE slug='{vendor_slug}'\""
    )
    if next_vendor_idx < len(_VENDOR_SLUGS):
        print(f"Then advance to next vendor: {_VENDOR_SLUGS[next_vendor_idx]}.")
    else:
        print("No further vendors in PE -> WWC -> TSA sequence; backfill complete.")
    print()


# ─── Vendor row fetch (bypasses fetch_vendor's active=true assertion) ─────────
def _fetch_vendor_row(client, slug: str) -> dict | None:
    """db.fetch_vendor() raises when vendors.active=false — but per the
    runbook, vendors.active is intentionally false during backfill (cron
    disabled). Direct fetch + soft warning if still active."""
    rows = (
        client.table("vendors")
        .select("id,slug,display_name,active")
        .eq("slug", slug)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


# ─── CLI entry ────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CTK-035 image-mirror compression backfill (one-vendor-at-a-time)",
    )
    parser.add_argument(
        "--vendor", required=True, choices=_VENDOR_SLUGS,
        help="Vendor slug to backfill",
    )
    parser.add_argument(
        "--phase", required=True, type=int, choices=(1, 3),
        help="1: per-object compress+upload + emit Phase 2 SQL; "
             "3: bulk-delete pre-rewrite paths (gated on Phase 2 integrity)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Phase 1 only: skip uploads + progress writes; log per-object byte deltas",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Phase 1 only: stop after N successful objects (smoke-run gate)",
    )
    args = parser.parse_args(argv)

    if args.phase != 1 and (args.dry_run or args.limit is not None):
        log.error("--dry-run and --limit are Phase 1 flags only")
        return 1

    client = db.get_client()
    vendor = _fetch_vendor_row(client, args.vendor)
    if vendor is None:
        log.error("vendors row not found for slug=%r", args.vendor)
        return 1
    if vendor["active"]:
        log.warning(
            "vendor %s is currently active=true. Per CTK-035 D-1 + D-4 runbook, "
            "disable cron BEFORE running Phase 1: "
            "supabase db query --linked \"UPDATE vendors SET active=false WHERE slug='%s'\"",
            args.vendor, args.vendor,
        )

    if args.phase == 1:
        result = run_phase1(client, vendor, dry_run=args.dry_run, limit=args.limit)
        print_phase1_summary(result, vendor["slug"], dry_run=args.dry_run)
        return 2 if result.fail_rate_pct > _FAIL_RATE_CEILING_PCT else 0

    if args.phase == 3:
        result = run_phase3(client, vendor)
        if result is None:
            return 1
        print_phase3_summary(result, vendor["slug"])
        return 0 if result.integrity_passed else 1

    return 1  # unreachable due to argparse choices


if __name__ == "__main__":
    sys.exit(main())
