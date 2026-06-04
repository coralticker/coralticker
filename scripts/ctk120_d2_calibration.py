"""CTK-120 D-2 calibration — 14d per-vendor listings_oos distribution from
scraper_runs (post-CTK-105 steady state), against current in_stock mass.

Confirms the default flip cap `max(50, 0.25 * prev_in_stock)` clears observed
legit OOS churn per vendor before constants lock. Read-only.

Run as: python -m scripts.ctk120_d2_calibration
"""

from __future__ import annotations

from scrapers.common.db import get_conn


def main() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT v.slug, "
                "       count(*) AS runs, "
                "       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.listings_oos) AS p50, "
                "       percentile_cont(0.95) WITHIN GROUP (ORDER BY r.listings_oos) AS p95, "
                "       max(r.listings_oos) AS max_oos "
                "FROM scraper_runs r JOIN vendors v ON v.id = r.vendor_id "
                "WHERE r.started_at >= now() - interval '14 days' "
                "  AND r.status IN ('success', 'partial') "
                "GROUP BY v.slug ORDER BY v.slug"
            )
            dist = {r["slug"]: r for r in cur.fetchall()}

            # Top-3 OOS runs per vendor — the tail the cap must clear.
            cur.execute(
                "SELECT slug, listings_oos, started_at FROM ("
                "  SELECT v.slug, r.listings_oos, r.started_at, "
                "         row_number() OVER (PARTITION BY v.slug ORDER BY r.listings_oos DESC) AS rn "
                "  FROM scraper_runs r JOIN vendors v ON v.id = r.vendor_id "
                "  WHERE r.started_at >= now() - interval '14 days' "
                "    AND r.status IN ('success', 'partial') "
                ") t WHERE rn <= 3 ORDER BY slug, listings_oos DESC"
            )
            top3: dict[str, list] = {}
            for r in cur.fetchall():
                top3.setdefault(r["slug"], []).append(
                    f"{r['listings_oos']} ({r['started_at']:%m-%d})"
                )

            cur.execute(
                "SELECT v.slug, count(*) FILTER (WHERE l.in_stock) AS in_stock_now "
                "FROM vendor_listings l JOIN vendors v ON v.id = l.vendor_id "
                "GROUP BY v.slug ORDER BY v.slug"
            )
            stock = {r["slug"]: r["in_stock_now"] for r in cur.fetchall()}

    hdr = f"{'vendor':<16}{'runs':>5}{'p50':>6}{'p95':>7}{'max':>6}{'in_stock':>10}{'cap':>7}{'headroom':>10}  top-3 oos runs"
    print(hdr)
    print("-" * len(hdr))
    for slug, d in dist.items():
        n = stock.get(slug, 0)
        cap = max(50, int(0.25 * n))
        max_oos = d["max_oos"] or 0
        headroom = cap - max_oos
        print(
            f"{slug:<16}{d['runs']:>5}{d['p50']:>6.0f}{d['p95']:>7.1f}{max_oos:>6}"
            f"{n:>10}{cap:>7}{headroom:>10}  {', '.join(top3.get(slug, []))}"
        )


if __name__ == "__main__":
    main()
