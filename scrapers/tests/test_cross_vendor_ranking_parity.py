"""scrapers/tests/test_cross_vendor_ranking_parity.py — CTK-161 Q1 refinement:
SQL <-> pure ranking parity for the cross-vendor cheapest signal (the single
highest-blast-radius signal in ig_select — the +100 score weight).

The ranking moved to SQL (get_cross_vendor_cheapest, migration 0038); the pure
cross_vendor_cheapest_ids is kept as its reference spec. This test feeds ONE
fixture to BOTH and asserts identical crowned-id sets — so a future divergence
(someone edits the SQL WHERE, or the pure ranker) fails loudly instead of
silently skewing what ig_select crowns.

Mechanism: seed the fixture into a ROLLED-BACK transaction (no committed writes),
then read the crowns two ways over the SAME real DB ids —
  - SQL:  SELECT ... FROM get_cross_vendor_cheapest() filtered to the seeded corals
  - pure: cross_vendor_cheapest_ids over the seeded rows read back raw
and assert the two id-sets are equal. No logical-id mapping (both use real ids),
no precomputed expected set (the two implementations cross-check each other; the
pure side is independently golden-pinned in test_content_queries).

DB-GATED: requires a live NEON_DATABASE_URL. Skips cleanly (exit 0) when no DB is
reachable — it is NOT part of the pure suite. Run it where a DB is available:
  python -m scrapers.tests.test_cross_vendor_ranking_parity

Scenarios mirror test_content_queries.RANKING_FIXTURE:
  coral 0  single-cheapest across 3 vendors   coral 3  cheaper auction excluded
  coral 1  price tie across 2 vendors          coral 4  cheaper OOS excluded
  coral 2  single vendor (no crown)            coral 5  null-price excluded
"""

from __future__ import annotations

import sys

from scrapers.tools.content_queries import cross_vendor_cheapest_ids

_AUCTION = "2099-01-01T00:00:00Z"

# (vendor_index, coral_index, price, in_stock, auction_end_time)
_SCENARIOS = [
    (0, 0, 10, True, None), (1, 0, 12, True, None), (2, 0, 15, True, None),
    (0, 1, 20, True, None), (1, 1, 20, True, None),
    (0, 2, 5, True, None),
    (0, 3, 8, True, _AUCTION), (1, 3, 30, True, None), (2, 3, 40, True, None),
    (0, 4, 5, False, None), (1, 4, 25, True, None), (2, 4, 35, True, None),
    (0, 5, None, True, None), (1, 5, 50, True, None), (2, 5, 55, True, None),
]


def _seed(cur):
    """Insert 3 vendors, 6 named_corals, and the scenario listings. Returns the
    list of seeded named_coral ids (to isolate the fixture from production rows)."""
    vendor_ids = []
    for i in range(3):
        cur.execute(
            "INSERT INTO vendors (slug, display_name, base_url, platform, scrape_method, cadence_label) "
            "VALUES (%s, %s, %s, 'shopify', 'products_json', 'hourly') RETURNING id",
            (f"ctk161-parity-v{i}", f"CTK161 Parity Vendor {i}", f"https://parity-{i}.invalid"),
        )
        vendor_ids.append(cur.fetchone()["id"])

    coral_ids = []
    for i in range(6):
        cur.execute(
            "INSERT INTO named_corals (canonical_name, normalized_name, slug, origin_vendor, coral_type, category) "
            "VALUES (%s, %s, %s, 'parity', 'lps', 1) RETURNING id",
            (f"CTK161 Parity Coral {i}", f"ctk161 parity coral {i}", f"ctk161-parity-coral-{i}"),
        )
        coral_ids.append(cur.fetchone()["id"])

    for n, (vi, ci, price, in_stock, auction) in enumerate(_SCENARIOS):
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, in_stock, current_price, "
            " named_coral_id, auction_end_time) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                vendor_ids[vi],
                f"https://parity-{vi}.invalid/p/{n}",
                f"parity listing {n}",
                f"parity listing {n}",
                in_stock,
                price,
                coral_ids[ci],
                auction,
            ),
        )
    return coral_ids


def test_sql_pure_ranking_parity(conn) -> None:
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            coral_ids = _seed(cur)

            # SQL crowns, isolated to the seeded corals.
            cur.execute(
                "SELECT id FROM get_cross_vendor_cheapest() WHERE named_coral_id = ANY(%s)",
                (coral_ids,),
            )
            sql_crowned = {r["id"] for r in cur.fetchall()}

            # Pure crowns over the SAME seeded rows read back raw.
            cur.execute(
                "SELECT id, vendor_id, named_coral_id, current_price, in_stock, auction_end_time "
                "FROM vendor_listings WHERE named_coral_id = ANY(%s)",
                (coral_ids,),
            )
            pure_crowned = cross_vendor_cheapest_ids(cur.fetchall())

        assert sql_crowned, "fixture produced no crowns — seeding likely failed"
        assert sql_crowned == pure_crowned, (
            f"SQL/pure ranking divergence: SQL={sorted(sql_crowned)} pure={sorted(pure_crowned)}"
        )
    finally:
        conn.rollback()


def _run_all() -> int:
    try:
        from scrapers.common import db
        conn = db.get_conn()
    except Exception as e:  # noqa: BLE001 — no DB reachable -> skip, not fail
        print(f"SKIP test_cross_vendor_ranking_parity: no DB ({type(e).__name__}: {e})")
        return 0

    try:
        test_sql_pure_ranking_parity(conn)
        print("ok   test_sql_pure_ranking_parity")
        print("\n1/1 passed")
        return 0
    except AssertionError as e:
        print(f"FAIL test_sql_pure_ranking_parity: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        # Most likely migration 0038 not applied yet (get_cross_vendor_cheapest
        # absent) -> skip, not fail. A genuine logic break surfaces as the
        # AssertionError above.
        import psycopg
        if isinstance(e, psycopg.errors.UndefinedFunction):
            print("SKIP test_cross_vendor_ranking_parity: migration 0038 not applied "
                  "(get_cross_vendor_cheapest absent)")
            return 0
        print(f"ERROR test_cross_vendor_ranking_parity: {type(e).__name__}: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(_run_all())
