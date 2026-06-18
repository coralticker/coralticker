"""CTK-170 Item C — read-only price-band distribution diagnostics.

Pulls the in-stock spotlight-candidate current_price distribution from prod Neon
so the Item C diversity bands (<$150 / $150-400 / $400-800 / $800+) are tuned to
real percentiles, not guessed (same candidate pool + same shape as
diag_ig_spotlight_thresholds.py / the MIN_SPOTLIGHT_PRICE pull). Reports both the
percentile spread and how the seed band edges partition the pool, so a band that
is near-empty or holds most of the mass surfaces before the edges are locked.
Read-only; no writes. Canonical agent path (scrapers.common.db.get_conn).

  python -m scripts.diag_ig_band_distribution
"""

from __future__ import annotations

from scrapers.common.db import get_conn

# Seed band edges (Item C D-2) — the partition this diag reports the fill of.
SEED_EDGES = (150.0, 400.0, 800.0)


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(q * (len(sorted_vals) - 1) + 0.5))
    return sorted_vals[i]


def _band(price, edges):
    for i, edge in enumerate(edges):
        if price < edge:
            return i
    return len(edges)


def main() -> int:
    with get_conn() as conn:
        # The realistic spotlight-candidate pool: in-stock, priced, non-auction —
        # AND above the MIN_SPOTLIGHT_PRICE floor (the banded set is the gate
        # survivors, so band the same population the guard scores over).
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT current_price
                FROM vendor_listings
                WHERE in_stock = true
                  AND current_price IS NOT NULL
                  AND auction_end_time IS NULL
                  AND is_auction = false
                  AND current_price >= 25.0
                """
            )
            prices = sorted(float(r["current_price"]) for r in cur.fetchall())

    if not prices:
        print("no candidate prices found")
        return 0

    print(f"=== in-stock priced non-auction candidate pool (>= $25 floor): n={len(prices)} ===")
    for q in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
        print(f"  p{int(q*100):>2} = ${_pct(prices, q):.2f}")
    print(f"  min=${prices[0]:.2f}  max=${prices[-1]:.2f}")

    labels = ["<$150", "$150-400", "$400-800", "$800+"]
    counts = [0, 0, 0, 0]
    for p in prices:
        counts[_band(p, SEED_EDGES)] += 1
    print(f"\n=== seed-edge band fill ({SEED_EDGES}) ===")
    for label, c in zip(labels, counts):
        print(f"  {label:>10}: {c:>5} / {len(prices)} = {100*c/len(prices):.1f}%")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
