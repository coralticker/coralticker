"""scrapers/tests/test_backfill_image_compression.py — CTK-035 Session 2
regression tests for scripts/backfill_image_compression.py three-phase
script (Phase 1 compress+upload+progress, Phase 3 integrity-gated bulk-delete).

Runnable as:
  python -m scrapers.tests.test_backfill_image_compression

No DB connection; no hosted-Supabase touch. Mock supabase client captures
.list/.download/.upload/.remove + .table().count via SimpleNamespace
shims. Each test runs inside an isolated tempdir to keep
.backfill-progress-*.json + .backfill-pre-rewrite-paths-*.json + .backfill-meta-*.json
files out of the repo working tree.

Coverage per /backend-engineer Session 2 directive:
  test_phase1_resumes_from_progress_file        — progress entries skip re-process
  test_phase1_pillow_failure_logs_and_continues — fail-soft per CTK-035 D-3
  test_phase1_skips_already_webp_objects        — forward-write outputs not re-processed
  test_phase1_dry_run_does_not_upload           — smoke-run gate semantics
  test_phase3_aborts_on_phase2_count_mismatch   — integrity check is gate, not just post-condition
  test_phase3_bulk_deletes_in_batches_of_100    — batch-of-100 cadence
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path

# Stub `supabase` so this file imports cleanly when run from a venv that
# lacks scrapers/requirements.txt — matches test_matcher.py + test_images_compress.py.
sys.modules.setdefault(
    "supabase",
    types.SimpleNamespace(Client=object, create_client=lambda *a, **k: None),
)

from scripts import backfill_image_compression as bf
from scrapers.common import images


# ─── Mock supabase client ─────────────────────────────────────────────────────
class _MockBucket:
    def __init__(
        self,
        list_objects: list[dict] | None = None,
        download_bytes: bytes = b"\xff\xd8\xff",  # JPEG magic; never actually decoded
    ):
        self._list_objects = list_objects or []
        self._download_bytes = download_bytes
        self.upload_calls: list[dict] = []
        self.remove_calls: list[list[str]] = []
        self.download_calls: list[str] = []

    def list(self, path, options):
        offset = options.get("offset", 0)
        limit = options.get("limit", bf._LIST_PAGE_SIZE)
        return self._list_objects[offset:offset + limit]

    def download(self, path):
        self.download_calls.append(path)
        return self._download_bytes

    def upload(self, **kwargs):
        self.upload_calls.append(kwargs)
        return types.SimpleNamespace(status_code=200)

    def remove(self, paths):
        self.remove_calls.append(list(paths))
        return types.SimpleNamespace(status_code=200)


class _MockStorage:
    def __init__(self, bucket: _MockBucket):
        self._bucket = bucket

    def from_(self, bucket_id):
        assert bucket_id == bf._BUCKET, f"unexpected bucket_id={bucket_id!r}"
        return self._bucket


class _MockTableQuery:
    def __init__(self, count_value: int):
        self._count = count_value

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def like(self, *a, **k):
        return self

    def execute(self):
        return types.SimpleNamespace(count=self._count, data=[])


class _MockClient:
    def __init__(self, bucket: _MockBucket, table_count: int = 0):
        self.storage = _MockStorage(bucket)
        self._table_count = table_count

    def table(self, name):
        return _MockTableQuery(self._table_count)


# ─── Fixture helpers ──────────────────────────────────────────────────────────
def _vendor(slug: str = "pacific_east", id_: int = 1) -> dict:
    return {"id": id_, "slug": slug, "display_name": "Test Vendor", "active": False}


def _make_listing(name: str) -> dict:
    return {"name": name}


def _stub_compress(monkey_patch_to: bytes = b"WEBP-OUT"):
    """Replace images._compress with a no-op that returns deterministic bytes.
    Tests aren't exercising real Pillow; the unit under test is the script's
    orchestration logic."""
    original = images._compress
    images._compress = lambda body: monkey_patch_to
    return original


def _restore_compress(original):
    images._compress = original


def _run_in_tempdir(test_fn):
    """Decorator: chdir to a fresh tempdir for the test body so progress
    files don't pollute the repo working tree. Restores CWD on exit."""
    def wrapped():
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            try:
                test_fn()
            finally:
                os.chdir(original_cwd)
    wrapped.__name__ = test_fn.__name__
    return wrapped


# ─── Test 1: progress file resume ─────────────────────────────────────────────
@_run_in_tempdir
def test_phase1_resumes_from_progress_file():
    """Pre-populate .backfill-progress-pacific_east.json with 5 entries; run
    Phase 1 with .list() returning 10 objects; assert only 5 are processed
    (the unseen 5). Progress file must contain all 10 entries at exit."""
    vendor = _vendor()
    listings = [_make_listing(f"coral-{i:02d}.jpg") for i in range(10)]

    pre_progress = [
        {
            "old_name": f"pacific_east/coral-{i:02d}.jpg",
            "new_name": f"pacific_east/coral-{i:02d}.webp",
            "bytes_old": 200_000,
            "bytes_new": 5_000,
        }
        for i in range(5)
    ]
    bf._atomic_write_json(bf._progress_path(vendor["slug"]), pre_progress)

    bucket = _MockBucket(list_objects=listings)
    client = _MockClient(bucket)

    original = _stub_compress()
    try:
        result = bf.run_phase1(client, vendor)
    finally:
        _restore_compress(original)

    assert result.total_discovered == 10, f"expected 10, got {result.total_discovered}"
    assert result.skipped_resumed == 5, f"expected 5 resumed, got {result.skipped_resumed}"
    assert result.succeeded == 5, f"expected 5 fresh successes, got {result.succeeded}"
    assert len(bucket.upload_calls) == 5, (
        f"expected 5 uploads (the unprocessed 5), got {len(bucket.upload_calls)}"
    )
    assert len(bucket.download_calls) == 5, (
        f"expected 5 downloads (skip happens before download for resumed entries), "
        f"got {len(bucket.download_calls)}"
    )

    final_progress = json.loads(bf._progress_path(vendor["slug"]).read_text(encoding="utf-8"))
    assert len(final_progress) == 10, f"expected 10 entries in final progress, got {len(final_progress)}"


# ─── Test 2: Pillow failure logs + continues (D-3 fail-soft) ─────────────────
@_run_in_tempdir
def test_phase1_pillow_failure_logs_and_continues():
    """Monkey-patch images._compress to raise on every 3rd call. With 9
    objects discovered, expect 3 failures + 6 successes; run completes
    cleanly; failure rate populated."""
    vendor = _vendor()
    listings = [_make_listing(f"coral-{i:02d}.jpg") for i in range(9)]

    bucket = _MockBucket(list_objects=listings)
    client = _MockClient(bucket)

    call_counter = {"n": 0}
    original = images._compress

    def flaky_compress(body):
        call_counter["n"] += 1
        if call_counter["n"] % 3 == 0:
            raise ValueError("synthetic Pillow decode failure")
        return b"WEBP-OUT"

    images._compress = flaky_compress
    try:
        result = bf.run_phase1(client, vendor)
    finally:
        images._compress = original

    assert call_counter["n"] == 9, f"expected 9 _compress calls, got {call_counter['n']}"
    assert result.pillow_failure_count == 3, (
        f"expected 3 failures (every 3rd of 9), got {result.pillow_failure_count}"
    )
    assert result.succeeded == 6, f"expected 6 successes, got {result.succeeded}"
    assert len(bucket.upload_calls) == 6, (
        f"failed compresses must NOT upload; expected 6 uploads, got {len(bucket.upload_calls)}"
    )
    assert abs(result.fail_rate_pct - (3 / 9 * 100.0)) < 0.01, (
        f"fail_rate_pct unexpected: {result.fail_rate_pct}"
    )


# ─── Test 3: skip already-.webp objects ──────────────────────────────────────
@_run_in_tempdir
def test_phase1_skips_already_webp_objects():
    """Mix .jpg + .webp in .list() return; only .jpg paths get processed.
    Forward-write outputs from Session 1's images.py change land as .webp;
    backfill must not re-process them."""
    vendor = _vendor()
    listings = [
        _make_listing("coral-00.jpg"),
        _make_listing("coral-01.webp"),
        _make_listing("coral-02.jpg"),
        _make_listing("coral-03.webp"),
        _make_listing("coral-04.jpg"),
    ]

    bucket = _MockBucket(list_objects=listings)
    client = _MockClient(bucket)

    original = _stub_compress()
    try:
        result = bf.run_phase1(client, vendor)
    finally:
        _restore_compress(original)

    assert result.skipped_already_webp == 2, (
        f"expected 2 .webp skips, got {result.skipped_already_webp}"
    )
    assert result.succeeded == 3, f"expected 3 .jpg processed, got {result.succeeded}"
    upload_paths = [c["path"] for c in bucket.upload_calls]
    assert all(p.endswith(".webp") for p in upload_paths), (
        f"all upload paths must rewrite to .webp; got {upload_paths}"
    )
    # No upload path should match a name that was already .webp in the listing.
    for original_webp in ("pacific_east/coral-01.webp", "pacific_east/coral-03.webp"):
        assert original_webp not in upload_paths, (
            f"already-.webp path {original_webp} was re-uploaded"
        )


# ─── Test 4: --dry-run does not upload + does not write progress file ────────
@_run_in_tempdir
def test_phase1_dry_run_does_not_upload():
    """--dry-run: .upload() must never be called, progress file must not
    be written. Smoke-run gate per directive (Jon sanity-checks PE on first
    50 objects before committing to the full run)."""
    vendor = _vendor()
    listings = [_make_listing(f"coral-{i:02d}.jpg") for i in range(5)]

    bucket = _MockBucket(list_objects=listings)
    client = _MockClient(bucket)

    original = _stub_compress()
    try:
        result = bf.run_phase1(client, vendor, dry_run=True)
    finally:
        _restore_compress(original)

    assert result.succeeded == 5, f"expected 5 dry-run successes, got {result.succeeded}"
    assert len(bucket.upload_calls) == 0, (
        f"dry-run must not upload; got {len(bucket.upload_calls)} uploads"
    )
    assert not bf._progress_path(vendor["slug"]).exists(), (
        "dry-run wrote progress file"
    )
    assert not bf._pre_rewrite_paths_path(vendor["slug"]).exists(), (
        "dry-run wrote pre-rewrite paths file"
    )
    assert not bf._meta_path(vendor["slug"]).exists(), (
        "dry-run wrote meta file"
    )


# ─── Test 5: Phase 3 aborts on Phase 2 count mismatch ────────────────────────
@_run_in_tempdir
def test_phase3_aborts_on_phase2_count_mismatch():
    """rows_webp = 100, bucket_webp = 95 → integrity fails → return value
    indicates abort + .remove() never called. Per plan.md acceptance line
    102 the count check is a gate, not just a post-condition."""
    vendor = _vendor()

    # Phase 3 prerequisite: pre-rewrite paths file must exist.
    bf._atomic_write_json(
        bf._pre_rewrite_paths_path(vendor["slug"]),
        [f"pacific_east/coral-{i:02d}.jpg" for i in range(100)],
    )

    # Bucket has 95 .webp objects (mismatch — Phase 2 SQL rewrote 100 rows
    # but only 95 made it into storage somehow; the gate must catch this).
    listings = [_make_listing(f"coral-{i:02d}.webp") for i in range(95)]

    bucket = _MockBucket(list_objects=listings)
    client = _MockClient(bucket, table_count=100)  # vendor_listings says 100

    result = bf.run_phase3(client, vendor)

    assert result is not None, "run_phase3 returned None when paths file was present"
    assert result.integrity_passed is False, "integrity should fail on count mismatch"
    assert result.rows_webp == 100, f"expected 100 vendor_listings rows, got {result.rows_webp}"
    assert result.bucket_webp == 95, f"expected 95 bucket .webp objects, got {result.bucket_webp}"
    assert result.deleted == 0, f"deleted count must be 0 on abort, got {result.deleted}"
    assert len(bucket.remove_calls) == 0, (
        f"bucket.remove() must not be called on abort; got {len(bucket.remove_calls)}"
    )


# ─── Test 6: Phase 3 bulk-deletes in batches of 100 ──────────────────────────
@_run_in_tempdir
def test_phase3_bulk_deletes_in_batches_of_100():
    """pre-rewrite paths file has 250 entries; assert .remove() called 3 times
    (100, 100, 50)."""
    vendor = _vendor()

    pre_rewrite_paths = [f"pacific_east/coral-{i:03d}.jpg" for i in range(250)]
    bf._atomic_write_json(bf._pre_rewrite_paths_path(vendor["slug"]), pre_rewrite_paths)

    # Match counts so integrity passes: 250 .webp rows + 250 .webp objects.
    listings = [_make_listing(f"coral-{i:03d}.webp") for i in range(250)]

    # Need 3 pages of 100 since _list_all_objects paginates at _LIST_PAGE_SIZE=100.
    # _MockBucket.list() handles offset slicing, so a 250-element list returns
    # [0:100], [100:200], [200:300]=50 across 3 list() calls.
    bucket = _MockBucket(list_objects=listings)
    client = _MockClient(bucket, table_count=250)

    result = bf.run_phase3(client, vendor)

    assert result is not None and result.integrity_passed, (
        f"integrity should pass; result={result}"
    )
    assert result.deleted == 250, f"expected 250 deleted, got {result.deleted}"
    assert len(bucket.remove_calls) == 3, (
        f"expected 3 .remove() calls (100+100+50), got {len(bucket.remove_calls)} "
        f"with batch sizes {[len(b) for b in bucket.remove_calls]}"
    )
    assert [len(b) for b in bucket.remove_calls] == [100, 100, 50], (
        f"batch sizes should be [100, 100, 50], got {[len(b) for b in bucket.remove_calls]}"
    )


# ─── Test runner ──────────────────────────────────────────────────────────────
TESTS = [
    test_phase1_resumes_from_progress_file,
    test_phase1_pillow_failure_logs_and_continues,
    test_phase1_skips_already_webp_objects,
    test_phase1_dry_run_does_not_upload,
    test_phase3_aborts_on_phase2_count_mismatch,
    test_phase3_bulk_deletes_in_batches_of_100,
]


def main() -> int:
    passed = 0
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001 — surface unexpected exception types
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed (total {len(TESTS)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
