"""scrapers/tests/test_first_seen_at.py — CTK-032 regression tests for
first_seen_at immutability on UPDATE-path + DB-DEFAULT-on-INSERT-payload-omit
+ batch-upsert column-set behavior verification.

Hits the live Neon Postgres via a psycopg connection (no local stub yet).
Uses a dedicated test vendor (slug='_ctk032_test', active=false) for
isolation — created on first run, listings wiped before + after each
test. Test vendor row stays in `vendors` between runs; cheap, no real-
scrape side-effects (active=false keeps it out of the cron orchestrator).

Runnable as:
  python -m scrapers.tests.test_first_seen_at

Requires NEON_DATABASE_URL in env (same as production scraper; auto-loaded
from .env at repo root via scrapers/common/db.py:44 load_dotenv()).

CTK-045 Session 1 2026-05-18: ported from supabase-py PostgREST surface
(client.table(...).select().eq().execute().data) to psycopg 3 raw SQL
(with conn.cursor() as cur: cur.execute(...); cur.fetchall()) mirroring
scrapers/tests/test_fetch_existing_listings_pagination.py's post-CTK-043
cut-1 shape. Tests 1-4 are mechanical ports — load-bearing assertions are
in the DB-side trigger + DEFAULT semantics, not the client surface.
cadence_label='daily' folded per open-items.md L42 (latent constraint
violation under vendors_cadence_label_check); masked today by hosted-DB
pre-existing _ctk032_test row, would fail on fresh-DB execution.

Test 5 (F3 cascade — test_column_omission_preserves_existing_under_batch_upsert)
retired per /lead-backend review-plan PASS-WITH-FOLDS 2026-05-18 (CTK-045
Q-1 disposition). Provenance comment block below the test bodies records
the retirement rationale and links the surviving production-code concern.

Coverage per CTK-032 plan §5 (post-retirement):
  test_first_seen_at_immutable_on_update                          (b2)
  test_first_seen_at_default_on_insert_when_payload_omits         (b1)-H1
  test_first_seen_at_preserved_on_update_when_payload_omits       (b1)-H2
  test_classify_vs_reality_drift_smoke                            mixed-payload smoke
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common import db

# CTK-039 D1 marker — pytest-aware so CI filter `-m "not requires_db"` skips
# this module's tests (live Neon Postgres). Script-mode invocation on a
# lean venv without pytest installed continues to work via the identity
# fallback.
try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


TEST_VENDOR_SLUG = "_ctk032_test"


def _setup_test_vendor(conn) -> dict:
    """Idempotent test-vendor setup. Returns the row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, slug, display_name, base_url, platform, image_strategy, active "
            "FROM vendors WHERE slug = %s",
            (TEST_VENDOR_SLUG,),
        )
        existing = cur.fetchall()
    if existing:
        return existing[0]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendors "
            "(slug, display_name, base_url, platform, scrape_method, "
            "cadence_label, image_strategy, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id, slug, display_name, base_url, platform, image_strategy, active",
            (
                TEST_VENDOR_SLUG,
                "CTK-032 test vendor",
                "https://example.test",
                "shopify",
                "products_json",
                "daily",  # CTK-045 fold of open-items.md L42 — 'test' violates vendors_cadence_label_check
                "mirror",
                False,
            ),
        )
        inserted = cur.fetchone()
    return inserted


def _wipe_listings(conn, vendor_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vendor_listings WHERE vendor_id = %s", (vendor_id,))


def _insert_row(conn, vendor_id: int, product_url: str, **extra) -> dict:
    """Single-row INSERT with optional extra columns. Returns the inserted row
    (id + caller-provided keys). first_seen_at can be passed via extra to
    seed the trigger preservation tests with a known timestamp.
    """
    payload = {
        "vendor_id": vendor_id,
        "product_url": product_url,
        "raw_title": extra.pop("raw_title", "test row"),
        "normalized_title": extra.pop("normalized_title", "test row"),
        "in_stock": extra.pop("in_stock", True),
        **extra,
    }
    cols = list(payload.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO vendor_listings ({col_list}) VALUES ({placeholders}) "
            f"RETURNING id, {col_list}",
            [payload[c] for c in cols],
        )
        return cur.fetchone()


def _upsert_rows(conn, rows: list[dict]) -> list[dict]:
    """Multi-row UPSERT with payload-driven column-set. Mirrors the production-code
    shape at scrapers/common/diff.py:369-393 _upsert_listing_row but in batch — every
    row in `rows` MUST share an identical key-set (otherwise the SET clause would
    union, which is the supabase-py PostgREST artifact CTK-045 retires Test 5 over).
    The batch form is used by Test 4 (mixed-decision chunk smoke) to reproduce the
    WWC 08:36 OOS-flip-in-mixed-chunk shape under psycopg3.

    Returns the result set from RETURNING (one row per input row).
    """
    if not rows:
        return []
    cols = list(rows[0].keys())
    keyset = set(cols)
    for r in rows[1:]:
        if set(r.keys()) != keyset:
            raise RuntimeError(
                f"_upsert_rows: chunk has heterogeneous key-sets — got {sorted(set(r.keys()))}, "
                f"expected {sorted(keyset)}. CTK-045 port preserves the production-code per-row "
                f"column-selective shape (diff.py:369-393); callers must pre-shape chunks."
            )
    placeholders_row = ", ".join(["%s"] * len(cols))
    values_clause = ", ".join([f"({placeholders_row})"] * len(rows))
    col_list = ", ".join(cols)
    update_set = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c not in ("vendor_id", "product_url")
    )
    flat = [r[c] for r in rows for c in cols]
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO vendor_listings ({col_list}) VALUES {values_clause} "
            f"ON CONFLICT (vendor_id, product_url) DO UPDATE SET {update_set} "
            f"RETURNING id, product_url",
            flat,
        )
        return cur.fetchall()


def _upsert_single(conn, payload: dict) -> dict:
    """Single-row UPSERT thin-wrapper over _upsert_rows for test ergonomics."""
    result = _upsert_rows(conn, [payload])
    return result[0]


def _select_row(conn, listing_id: int, columns: str = "*") -> dict:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {columns} FROM vendor_listings WHERE id = %s",
            (listing_id,),
        )
        return cur.fetchone()


# ─── Test 1: trigger preserves OLD on UPDATE when payload includes first_seen_at ──
@mark_requires_db
def test_first_seen_at_immutable_on_update(conn, vendor):
    """(b2) coverage. INSERT a row with first_seen_at=T0, then UPSERT the
    same row with first_seen_at=T1 in the payload. Trigger must preserve T0.
    """
    _wipe_listings(conn, vendor["id"])
    t0 = "2025-01-01T00:00:00+00:00"
    seeded = _insert_row(conn, vendor["id"], "https://example.test/p/immutable", first_seen_at=t0)
    t0_actual = _select_row(conn, seeded["id"], "first_seen_at")["first_seen_at"]

    t1 = "2099-12-31T23:59:59+00:00"
    _upsert_single(conn, {
        "vendor_id": vendor["id"],
        "product_url": "https://example.test/p/immutable",
        "raw_title": "test row",
        "normalized_title": "test row",
        "in_stock": True,
        "first_seen_at": t1,
    })

    after = _select_row(conn, seeded["id"], "first_seen_at")["first_seen_at"]
    assert after == t0_actual, (
        f"trigger failed to preserve first_seen_at on UPDATE-with-payload: "
        f"expected {t0_actual!r}, got {after!r}"
    )


# ─── Test 2: DB DEFAULT fires when payload omits first_seen_at on INSERT ──────
@mark_requires_db
def test_first_seen_at_default_on_insert_when_payload_omits(conn, vendor):
    """(b1)-H1 coverage. UPSERT a row with first_seen_at OMITTED. Since this
    row does not pre-exist, INSERT-path fires. DB DEFAULT now() must populate
    first_seen_at; the row must NOT have NULL.
    """
    _wipe_listings(conn, vendor["id"])
    inserted = _upsert_single(conn, {
        "vendor_id": vendor["id"],
        "product_url": "https://example.test/p/insert-default",
        "raw_title": "test row",
        "normalized_title": "test row",
        "in_stock": True,
        # first_seen_at intentionally omitted
    })

    after = _select_row(conn, inserted["id"], "first_seen_at")["first_seen_at"]
    assert after is not None, (
        f"DB DEFAULT failed to populate first_seen_at on INSERT-payload-omit: got NULL"
    )


# ─── Test 3: first_seen_at preserved on UPDATE when payload omits it ──────────
@mark_requires_db
def test_first_seen_at_preserved_on_update_when_payload_omits(conn, vendor):
    """(b1)-H2 coverage — homogeneous-payload UPDATE-path. INSERT a row with
    first_seen_at=T0, then UPSERT a chunk where this row omits first_seen_at
    (and the rest of the chunk also omits it). The SET clause built by
    _upsert_rows from the payload's keys excludes first_seen_at; UPDATE-path
    leaves OLD intact.
    """
    _wipe_listings(conn, vendor["id"])
    t0 = "2024-06-15T12:00:00+00:00"
    seeded = _insert_row(conn, vendor["id"], "https://example.test/p/preserve-omit", first_seen_at=t0)
    t0_actual = _select_row(conn, seeded["id"], "first_seen_at")["first_seen_at"]

    _upsert_single(conn, {
        "vendor_id": vendor["id"],
        "product_url": "https://example.test/p/preserve-omit",
        "raw_title": "test row",
        "normalized_title": "test row",
        "in_stock": False,  # forces an UPDATE-shaped change without re-asserting first_seen_at
        # first_seen_at intentionally omitted from payload + SET clause
    })

    after = _select_row(conn, seeded["id"], "first_seen_at")["first_seen_at"]
    assert after == t0_actual, (
        f"first_seen_at clobbered on UPDATE-with-payload-omit: "
        f"expected {t0_actual!r}, got {after!r}"
    )


# ─── Test 4: post-fix mixed-decision chunk — WWC 08:36 reproduction ───────────
@mark_requires_db
def test_classify_vs_reality_drift_smoke(conn, vendor):
    """End-to-end reproduction of the WWC 08:36:23Z + 12:15:22Z failure shape
    against post-fix production code. Mixed-decision chunk (multiple new +
    one existing, all omitting first_seen_at — the diff.py post-fix shape).
    Uses LSCM26AQF-39-45 as the repro vendor_sku per /reef-lead correction
    directive 2026-05-05.

    Pre-fix (supabase-py PostgREST): the existing row's payload omitted
    first_seen_at while sibling new-row payloads included it -> PostgREST
    union'd column-set -> speculative INSERT for the UPDATE-path row had
    first_seen_at=NULL -> NOT NULL fired before ON CONFLICT routed to
    UPDATE-path (trigger never invoked). Whole chunk rolled back.

    Post-fix (psycopg ON CONFLICT DO UPDATE): NO row anywhere includes
    first_seen_at -> column-set is identical across rows in the chunk ->
    SET clause excludes first_seen_at -> INSERT-path rows land cleanly
    with DB DEFAULT now() + UPDATE-path row's existing first_seen_at
    preserved (column not in SET clause, trigger not invoked). Note: the
    PostgREST union-cascade pre-fix root cause is structurally absent under
    psycopg3 because _upsert_rows enforces homogeneous key-sets per chunk,
    matching the production-code shape at diff.py:369-393.
    """
    _wipe_listings(conn, vendor["id"])
    t0 = "2024-06-15T12:00:00+00:00"
    seeded = _insert_row(
        conn, vendor["id"],
        "https://example.test/p/lscm26aqf-39-45",
        vendor_sku="LSCM26AQF-39-45",
        raw_title="WWC Knockout Rainbow Chalice",
        normalized_title="wwc knockout rainbow chalice",
        first_seen_at=t0,
    )
    t0_actual = _select_row(conn, seeded["id"], "first_seen_at")["first_seen_at"]

    response = _upsert_rows(conn, [
        {
            "vendor_id": vendor["id"],
            "product_url": "https://example.test/p/drift-new-1",
            "raw_title": "test row",
            "normalized_title": "test row",
            "in_stock": True,
            # first_seen_at omitted — post-fix production-code shape
        },
        {
            "vendor_id": vendor["id"],
            "product_url": "https://example.test/p/lscm26aqf-39-45",
            "raw_title": "WWC Knockout Rainbow Chalice",
            "normalized_title": "wwc knockout rainbow chalice",
            "in_stock": False,  # OOS-flip — same shape as the WWC 08:36 OOS row
            # first_seen_at omitted — UPDATE-path row in mixed chunk
        },
        {
            "vendor_id": vendor["id"],
            "product_url": "https://example.test/p/drift-new-2",
            "raw_title": "test row",
            "normalized_title": "test row",
            "in_stock": True,
            # first_seen_at omitted
        },
    ])

    assert len(response) == 3, f"expected 3 rows in upsert response, got {len(response)}"

    # Both NEW rows — INSERT path, DB DEFAULT now() landed.
    for url_suffix in ("/drift-new-1", "/drift-new-2"):
        row = next(r for r in response if r["product_url"].endswith(url_suffix))
        full = _select_row(conn, row["id"], "first_seen_at")
        assert full["first_seen_at"] is not None, (
            f"NEW row at {url_suffix}: DB DEFAULT didn't fire on INSERT-payload-omit"
        )

    # EXISTING row (UPDATE-path) — first_seen_at preserved + in_stock updated.
    existing_after = _select_row(conn, seeded["id"], "first_seen_at, in_stock")
    assert existing_after["first_seen_at"] == t0_actual, (
        f"UPDATE-path row's first_seen_at clobbered: expected {t0_actual!r}, got {existing_after['first_seen_at']!r}"
    )
    assert existing_after["in_stock"] is False, (
        f"UPDATE-path row's in_stock didn't update: expected False, got {existing_after['in_stock']!r}"
    )


# ─── Retired: Test 5 (F3 cascade — column-omission preserves existing on UPDATE-path)
#
# Pre-CTK-045 this file carried a fifth test:
#   test_column_omission_preserves_existing_under_batch_upsert
#
# It documented the F3 cascade observation from CTK-032 — under supabase-py
# PostgREST, a mixed-key-set chunk (existing row omits image_url +
# current_price; sibling row includes them) unioned the column-set across
# rows, sending NULL for the omitted columns on the UPDATE-path row.
# Original test was documented to FAIL until CTK-024's retro-fix landed;
# the AssertionError body served as living-doc for the cascade.
#
# CTK-045 retires the test per /lead-backend review-plan PASS-WITH-FOLDS
# 2026-05-18 (Q-1 disposition). Three reasons:
#
#   1. CTK-032 F3 origin context. The cascade was first observed against
#      supabase-py PostgREST's batch-upsert column-set inference — the
#      client unioned keys across chunk rows before sending the SQL to
#      Postgres. That client-side union was the artifact-generator; the
#      DB-side trigger machinery didn't produce it.
#
#   2. supabase-py PostgREST batch-union root cause. Post-CTK-043 cut-1
#      (2026-05-16) the data-plane no longer uses PostgREST. The
#      column-set-union behavior the test probed is no longer a transport
#      surface that exists on the codepath.
#
#   3. Per-row column-selective SET shape under psycopg3. Production
#      writes go through scrapers/common/diff.py:369-393 _upsert_listing_row,
#      which builds the column list + SET clause from each row's actual
#      keys before issuing INSERT ... ON CONFLICT DO UPDATE. Batch
#      callers shape chunks to homogeneous key-sets (CTK-024 / CTK-025
#      match-field preservation + image_url-on-NEW-only dispositions
#      shipped exactly this discipline); _upsert_rows above enforces it.
#      A chunk with heterogeneous key-sets is rejected at the helper
#      boundary rather than silently union-ing — no transport-layer
#      cascade surface remains to test.
#
# The CTK-024 retro-fix question (whether column-omission preserves
# existing values on UPDATE-path) survives independently in production
# code: it's an invariant of the diff.py column-selective shape, not a
# transport-layer artifact. Reopens via CTK-024 retro-fix scoping if a
# real downstream consumer's behavior diverges; the living-doc role of
# this test no longer applies.
#
# ──────────────────────────────────────────────────────────────────────


def main() -> int:
    with db.get_conn() as conn:
        vendor = _setup_test_vendor(conn)
        print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")

        tests = [
            test_first_seen_at_immutable_on_update,
            test_first_seen_at_default_on_insert_when_payload_omits,
            test_first_seen_at_preserved_on_update_when_payload_omits,
            test_classify_vs_reality_drift_smoke,
        ]

        failures: list[tuple[str, str]] = []
        for fn in tests:
            name = fn.__name__
            try:
                fn(conn, vendor)
                print(f"  [PASS] {name}")
            except AssertionError as e:
                print(f"  [FAIL] {name}: {e}")
                failures.append((name, str(e)))
            except Exception as e:  # noqa: BLE001
                print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
                traceback.print_exc()
                failures.append((name, f"{type(e).__name__}: {e}"))
            finally:
                try:
                    _wipe_listings(conn, vendor["id"])
                except Exception as e:  # noqa: BLE001
                    print(f"  [cleanup-warn] {name}: {e}")

        print()
        if failures:
            print(f"{len(failures)}/{len(tests)} tests failed:")
            for name, msg in failures:
                print(f"  - {name}: {msg[:200]}")
            return 1
        print(f"all {len(tests)} tests passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
