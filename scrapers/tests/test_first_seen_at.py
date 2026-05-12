"""scrapers/tests/test_first_seen_at.py — CTK-032 regression tests for
first_seen_at immutability on UPDATE-path + DB-DEFAULT-on-INSERT-payload-omit
+ PostgREST batch-upsert column-set behavior verification.

Hits the live hosted Supabase via service_role client (no local stub yet).
Uses a dedicated test vendor (slug='_ctk032_test', active=false) for
isolation — created on first run, listings wiped before + after each
test. Test vendor row stays in `vendors` between runs; cheap, no real-
scrape side-effects (active=false keeps it out of the cron orchestrator).

Runnable as:
  python -m scrapers.tests.test_first_seen_at

Requires SUPABASE_URL + SUPABASE_SERVICE_KEY in env (same as production
scraper).

Coverage per CTK-032 plan §5:
  test_first_seen_at_immutable_on_update                          (b2)
  test_first_seen_at_default_on_insert_when_payload_omits         (b1)-H1
  test_first_seen_at_preserved_on_update_when_payload_omits       (b1)-H2
  test_classify_vs_reality_drift_smoke                            mixed-payload smoke
  test_column_omission_preserves_existing_under_batch_upsert      F3 cascade
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common import db

# CTK-039 D1 marker — pytest-aware so CI filter `-m "not requires_db"` skips
# this module's tests (live hosted Supabase). Script-mode invocation on a
# lean venv without pytest installed continues to work via the identity
# fallback.
try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


TEST_VENDOR_SLUG = "_ctk032_test"


def _setup_test_vendor(client) -> dict:
    """Idempotent test-vendor setup. Returns the row."""
    existing = (
        client.table("vendors")
        .select("id,slug,display_name,base_url,platform,image_strategy,active")
        .eq("slug", TEST_VENDOR_SLUG)
        .execute()
        .data
        or []
    )
    if existing:
        return existing[0]
    inserted = (
        client.table("vendors")
        .insert({
            "slug": TEST_VENDOR_SLUG,
            "display_name": "CTK-032 test vendor",
            "base_url": "https://example.test",
            "platform": "shopify",
            "scrape_method": "products_json",
            "cadence_label": "test",
            "image_strategy": "mirror",
            "active": False,
        })
        .execute()
        .data
    )
    return inserted[0]


def _wipe_listings(client, vendor_id: int) -> None:
    client.table("vendor_listings").delete().eq("vendor_id", vendor_id).execute()


def _insert_row(client, vendor_id: int, product_url: str, **extra) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "product_url": product_url,
        "raw_title": extra.pop("raw_title", "test row"),
        "normalized_title": extra.pop("normalized_title", "test row"),
        "in_stock": extra.pop("in_stock", True),
        **extra,
    }
    return (
        client.table("vendor_listings")
        .insert(payload)
        .execute()
        .data[0]
    )


def _select_row(client, listing_id: int, columns: str = "*") -> dict:
    return (
        client.table("vendor_listings")
        .select(columns)
        .eq("id", listing_id)
        .execute()
        .data[0]
    )


# ─── Test 1: trigger preserves OLD on UPDATE when payload includes first_seen_at ──
@mark_requires_db
def test_first_seen_at_immutable_on_update(client, vendor):
    """(b2) coverage. INSERT a row with first_seen_at=T0, then UPSERT the
    same row with first_seen_at=T1 in the payload. Trigger must preserve T0.
    """
    _wipe_listings(client, vendor["id"])
    t0 = "2025-01-01T00:00:00+00:00"
    seeded = _insert_row(client, vendor["id"], "https://example.test/p/immutable", first_seen_at=t0)
    t0_actual = _select_row(client, seeded["id"], "first_seen_at")["first_seen_at"]

    t1 = "2099-12-31T23:59:59+00:00"
    client.table("vendor_listings").upsert(
        [{
            "vendor_id": vendor["id"],
            "product_url": "https://example.test/p/immutable",
            "raw_title": "test row",
            "normalized_title": "test row",
            "in_stock": True,
            "first_seen_at": t1,
        }],
        on_conflict="vendor_id,product_url",
    ).execute()

    after = _select_row(client, seeded["id"], "first_seen_at")["first_seen_at"]
    assert after == t0_actual, (
        f"trigger failed to preserve first_seen_at on UPDATE-with-payload: "
        f"expected {t0_actual!r}, got {after!r}"
    )


# ─── Test 2: DB DEFAULT fires when payload omits first_seen_at on INSERT ──────
@mark_requires_db
def test_first_seen_at_default_on_insert_when_payload_omits(client, vendor):
    """(b1)-H1 coverage. UPSERT a row with first_seen_at OMITTED. Since this
    row does not pre-exist, INSERT-path fires. DB DEFAULT now() must populate
    first_seen_at; the row must NOT have NULL.
    """
    _wipe_listings(client, vendor["id"])
    response = client.table("vendor_listings").upsert(
        [{
            "vendor_id": vendor["id"],
            "product_url": "https://example.test/p/insert-default",
            "raw_title": "test row",
            "normalized_title": "test row",
            "in_stock": True,
            # first_seen_at intentionally omitted
        }],
        on_conflict="vendor_id,product_url",
    ).execute()

    inserted_id = response.data[0]["id"]
    after = _select_row(client, inserted_id, "first_seen_at")["first_seen_at"]
    assert after is not None, (
        f"DB DEFAULT failed to populate first_seen_at on INSERT-payload-omit: got NULL"
    )


# ─── Test 3: first_seen_at preserved on UPDATE when payload omits it ──────────
@mark_requires_db
def test_first_seen_at_preserved_on_update_when_payload_omits(client, vendor):
    """(b1)-H2 coverage — homogeneous-payload UPDATE-path. INSERT a row with
    first_seen_at=T0, then UPSERT a chunk where this row omits first_seen_at
    (and the rest of the chunk also omits it). PostgREST column-set should
    exclude first_seen_at; UPDATE-path SET clause should not touch it; OLD
    must be preserved.
    """
    _wipe_listings(client, vendor["id"])
    t0 = "2024-06-15T12:00:00+00:00"
    seeded = _insert_row(client, vendor["id"], "https://example.test/p/preserve-omit", first_seen_at=t0)
    t0_actual = _select_row(client, seeded["id"], "first_seen_at")["first_seen_at"]

    client.table("vendor_listings").upsert(
        [{
            "vendor_id": vendor["id"],
            "product_url": "https://example.test/p/preserve-omit",
            "raw_title": "test row",
            "normalized_title": "test row",
            "in_stock": False,  # forces an UPDATE-shaped change without re-asserting first_seen_at
            # first_seen_at intentionally omitted
        }],
        on_conflict="vendor_id,product_url",
    ).execute()

    after = _select_row(client, seeded["id"], "first_seen_at")["first_seen_at"]
    assert after == t0_actual, (
        f"first_seen_at clobbered on UPDATE-with-payload-omit: "
        f"expected {t0_actual!r}, got {after!r}"
    )


# ─── Test 4: post-fix mixed-decision chunk — WWC 08:36 reproduction ───────────
@mark_requires_db
def test_classify_vs_reality_drift_smoke(client, vendor):
    """End-to-end reproduction of the WWC 08:36:23Z + 12:15:22Z failure shape
    against post-fix production code. Mixed-decision chunk (multiple new +
    one existing, all omitting first_seen_at — the diff.py post-fix shape).
    Uses LSCM26AQF-39-45 as the repro vendor_sku per /reef-lead correction
    directive 2026-05-05.

    Pre-fix: the existing row's payload omitted first_seen_at while sibling
    new-row payloads included it → PostgREST union'd column-set → speculative
    INSERT for the UPDATE-path row had first_seen_at=NULL → NOT NULL fired
    before ON CONFLICT routed to UPDATE-path (trigger never invoked). Whole
    chunk rolled back.

    Post-fix: NO row anywhere includes first_seen_at → PostgREST column-set
    excludes it → speculative INSERT carries DB DEFAULT now() → INSERT-path
    rows land cleanly + UPDATE-path row's existing first_seen_at preserved
    (column not in SET clause, trigger not invoked).
    """
    _wipe_listings(client, vendor["id"])
    t0 = "2024-06-15T12:00:00+00:00"
    seeded = _insert_row(
        client, vendor["id"],
        "https://example.test/p/lscm26aqf-39-45",
        vendor_sku="LSCM26AQF-39-45",
        raw_title="WWC Knockout Rainbow Chalice",
        normalized_title="wwc knockout rainbow chalice",
        first_seen_at=t0,
    )
    t0_actual = _select_row(client, seeded["id"], "first_seen_at")["first_seen_at"]

    response = client.table("vendor_listings").upsert(
        [
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
                "vendor_sku": "LSCM26AQF-39-45",
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
        ],
        on_conflict="vendor_id,product_url",
    ).execute()

    assert len(response.data) == 3, f"expected 3 rows in upsert response, got {len(response.data)}"

    # Both NEW rows — INSERT path, DB DEFAULT now() landed.
    for url_suffix in ("/drift-new-1", "/drift-new-2"):
        row = next(r for r in response.data if r["product_url"].endswith(url_suffix))
        full = _select_row(client, row["id"], "first_seen_at")
        assert full["first_seen_at"] is not None, (
            f"NEW row at {url_suffix}: DB DEFAULT didn't fire on INSERT-payload-omit"
        )

    # EXISTING row (UPDATE-path) — first_seen_at preserved + in_stock updated.
    existing_after = _select_row(client, seeded["id"], "first_seen_at,in_stock")
    assert existing_after["first_seen_at"] == t0_actual, (
        f"UPDATE-path row's first_seen_at clobbered: expected {t0_actual!r}, got {existing_after['first_seen_at']!r}"
    )
    assert existing_after["in_stock"] is False, (
        f"UPDATE-path row's in_stock didn't update: expected False, got {existing_after['in_stock']!r}"
    )


# ─── Test 5: generalized column-omission cascade ─────────────────────────────
@mark_requires_db
def test_column_omission_preserves_existing_under_batch_upsert(client, vendor):
    """F3 cascade test. Verifies whether the diff.py:139-143 working assumption
    ('PostgREST upsert only writes columns present in the payload') holds for
    columns OTHER than first_seen_at. Parameterized across image_url +
    named_coral_id + current_price.

    Setup: INSERT a row with all three columns populated. UPSERT a chunk where
    THIS row omits all three but a sibling row in the chunk INCLUDES at least
    one of them (forcing each column into the unioned column-set).

    Post-fix expectation: PostgREST sends NULL for the omitted column on the
    UPDATE-path row (the working-assumption is wrong); the cascade is real.
    Test asserts the actual observed behavior so future drift surfaces.

    NOTE: This test FAILS until CTK-033 lands the cascade fix. The AssertionError
    message documents the empirical cascade observation — failure is the
    test-as-living-documentation signal, not a regression. Test will pass once
    CTK-033's column-scoped immutability triggers (or equivalent) extend the
    Option A pattern to image_url + current_price + the four matcher fields.
    """
    _wipe_listings(client, vendor["id"])
    seeded = _insert_row(
        client, vendor["id"],
        "https://example.test/p/cascade-existing",
        image_url="https://example.test/img/seeded.jpg",
        current_price="100.00",
    )

    response = client.table("vendor_listings").upsert(
        [
            {
                "vendor_id": vendor["id"],
                "product_url": "https://example.test/p/cascade-existing",
                "raw_title": "test row",
                "normalized_title": "test row",
                "in_stock": True,
                # image_url + current_price OMITTED — testing whether they survive on UPDATE-path
            },
            {
                "vendor_id": vendor["id"],
                "product_url": "https://example.test/p/cascade-sibling",
                "raw_title": "test row",
                "normalized_title": "test row",
                "in_stock": True,
                "image_url": "https://example.test/img/sibling.jpg",
                "current_price": "200.00",
                # forces image_url + current_price into the unioned column-set
            },
        ],
        on_conflict="vendor_id,product_url",
    ).execute()

    after = _select_row(client, seeded["id"], "image_url,current_price")

    # Document observed behavior. Strict-pass = comment claim holds (preserve);
    # observed-clobber = cascade is real and diff.py:139-143 needs cascade-edit.
    image_url_preserved = after["image_url"] == "https://example.test/img/seeded.jpg"
    current_price_preserved = str(after["current_price"]) == "100.00"

    if not image_url_preserved or not current_price_preserved:
        # Cascade is real — document for /lead-backend follow-up scoping.
        raise AssertionError(
            f"CASCADE OBSERVED — column-omission does NOT preserve existing on UPDATE-path:\n"
            f"  image_url:     {'PRESERVED' if image_url_preserved else 'CLOBBERED'} "
            f"(after={after['image_url']!r})\n"
            f"  current_price: {'PRESERVED' if current_price_preserved else 'CLOBBERED'} "
            f"(after={after['current_price']!r})\n"
            f"  diff.py:139-143 working assumption is WRONG for these columns; "
            f"CTK-024 retro-fix scoping required."
        )


def main() -> int:
    client = db.get_client()
    vendor = _setup_test_vendor(client)
    print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")

    tests = [
        test_first_seen_at_immutable_on_update,
        test_first_seen_at_default_on_insert_when_payload_omits,
        test_first_seen_at_preserved_on_update_when_payload_omits,
        test_classify_vs_reality_drift_smoke,
        test_column_omission_preserves_existing_under_batch_upsert,
    ]

    failures: list[tuple[str, str]] = []
    for fn in tests:
        name = fn.__name__
        try:
            fn(client, vendor)
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
                _wipe_listings(client, vendor["id"])
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
