"""scrapers/tests/test_canary_gates_persist.py — CTK-116 D-3 failed-run
write-integrity tests.

D-1 (canary gates persist): a canary-tripped run must not invoke
diff.persist_phase_a — zero data-plane footprint on failed runs. The
scraper_runs observability row still lands with full counters (the
get_7d_median_seen ratchet reads listings_seen off canary-only failures)
and an error_message carrying BOTH the ratchet-LIKE substring
('silent canary tripped:' — contains-match per db.py) AND the CTK-116
'persist skipped (canary)' disambiguator clause.

D-2 (Phase A atomicity): diff.persist_phase_a runs its write blocks inside
one conn.transaction() context. Per the /review-plan note, the test asserts
the transaction context was ENTERED (and sees the injected exception on
__exit__, so real psycopg would roll back) rather than mocking rollback
semantics — a mock can't meaningfully simulate what BEGIN/ROLLBACK does.

Orchestrator-level tests mock the db module boundary + parser and execute
the real run.run() control flow (real diff.classify, real canary math,
real status assignment). No DB, no network.

Runnable as:
  python -m scrapers.tests.test_canary_gates_persist
"""

from __future__ import annotations

import sys
import traceback
from decimal import Decimal
from unittest import mock

from scrapers.common import run as run_mod
from scrapers.common.diff import ItemDecision, persist_phase_a
from scrapers.common.parse_shopify import ParseResult


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


VENDOR_ROW = {
    "id": 7,
    "slug": "tsa",
    "display_name": "Top Shelf Aquatics",
    "base_url": "https://topshelfaquatics.example",
    "platform": "shopify",
    "scrape_method": "products_json",
    "cadence_label": "hourly",
    "image_strategy": "hotlink",
    "active": True,
}


def _make_item(product_url: str) -> dict:
    """Real-parser item shape (parse_shopify._normalize_product)."""
    return {
        "product_url": product_url,
        "raw_title": f"Title for {product_url}",
        "normalized_title": f"title for {product_url}",
        "current_price": Decimal("25.00"),
        "currency": "USD",
        "in_stock": True,
        "category": "sps",
        "lineage_flag": "unknown",
        "vendor_sku": None,
        "vendor_image_url": None,
    }


def _run_orchestrator(n_items: int, median_seen: float, n_new: int = 0, matcher_exc: Exception | None = None):
    """Execute run.run('tsa') with the db module boundary + parser mocked.

    By default all n_items exist in the DB as unchanged rows (no 'new'
    decisions, so the matcher loop is a no-op). The first n_new items are
    absent from the DB instead ('new' decisions — the matcher runs on them);
    matcher_exc, when set, makes the patched matcher raise it (fail-soft
    path: matcher_error_count accumulates into error_message). Real
    diff.classify + real canary threshold math + real status assignment run.

    Returns (exit_code, persist_spy, finish_spy, phase_b_spy).
    """
    items = [_make_item(f"https://topshelfaquatics.example/products/c-{i}") for i in range(n_items)]
    existing = {
        it["product_url"]: {
            "id": i + 1,
            "product_url": it["product_url"],
            "current_price": Decimal("25.00"),
            "in_stock": True,
            "image_url": None,
        }
        for i, it in enumerate(items)
        if i >= n_new  # first n_new items absent from DB → 'new' decisions
    }
    parse_result = ParseResult(
        items=items,
        html_hash="testhash",
        http_status_last=200,
        pages_fetched=1,
        per_category_counts={},
        filtered_urls=set(),
    )
    with mock.patch.object(run_mod.db, "get_conn", return_value=mock.MagicMock()), \
         mock.patch.object(run_mod.db, "fetch_vendor", return_value=VENDOR_ROW), \
         mock.patch.object(run_mod.db, "start_scraper_run", return_value=42), \
         mock.patch.object(run_mod, "_load_yaml", return_value={}), \
         mock.patch.object(run_mod.matcher, "load_match_cache", return_value={}), \
         mock.patch.object(run_mod.matcher, "match_listing", side_effect=matcher_exc), \
         mock.patch.object(run_mod.parse_shopify, "fetch_and_parse", return_value=parse_result), \
         mock.patch.object(run_mod.db, "fetch_existing_listings", return_value=existing), \
         mock.patch.object(run_mod.db, "get_7d_median_seen", return_value=median_seen), \
         mock.patch.object(run_mod.db, "get_7d_median_pages_fetched", return_value=0.0), \
         mock.patch.object(run_mod.diff, "persist_phase_a", return_value=[]) as persist_spy, \
         mock.patch.object(run_mod.db, "finish_scraper_run") as finish_spy, \
         mock.patch.object(run_mod.db, "finish_phase_b") as phase_b_spy:
        exit_code = run_mod.run("tsa")
    return exit_code, persist_spy, finish_spy, phase_b_spy


# ---------------------------------------------------------------------------
# D-1 (i) — canary trip skips persist entirely
# ---------------------------------------------------------------------------


def test_canary_trip_skips_persist_phase_a():
    """3 items vs 7d-median 1000 → threshold max(5, 200) = 200 → canary
    trips. persist_phase_a MUST NOT be invoked; exit code 1; Phase B
    untouched (status='failed' gates it independently)."""
    exit_code, persist_spy, finish_spy, phase_b_spy = _run_orchestrator(
        n_items=3, median_seen=1000.0,
    )
    assert exit_code == 1
    persist_spy.assert_not_called()
    phase_b_spy.assert_not_called()
    finish_spy.assert_called_once()


def test_canary_trip_counters_flow_to_finish():
    """/review-plan note #1 — counters must flow to finish_scraper_run on
    the failed run: get_7d_median_seen's ratchet inclusion reads
    listings_seen off canary-only failures, so a zeroed Counters here would
    silently bias the median upward after every false trip."""
    _, _, finish_spy, _ = _run_orchestrator(n_items=3, median_seen=1000.0)
    args = finish_spy.call_args.args
    # finish_scraper_run(conn, run_id, status, error_class, error_message,
    #                    counters, html_hash, http_status_last, ...)
    status, error_class, error_message, counters = args[2], args[3], args[4], args[5]
    assert status == "failed"
    assert error_class == "block"
    assert counters.seen == 3  # classified-but-not-persisted work, still counted
    assert args[6] == "testhash"  # html_hash flows too


def test_canary_trip_error_message_substrings():
    """D-1 error_message contract: the ratchet-LIKE substring
    'silent canary tripped:' survives EXACTLY (db.py get_7d_median_seen
    keys on contains-LIKE '%silent canary tripped:%') and the
    'persist skipped (canary)' disambiguator clause is appended after it."""
    _, _, finish_spy, _ = _run_orchestrator(n_items=3, median_seen=1000.0)
    error_message = finish_spy.call_args.args[4]
    assert "silent canary tripped:" in error_message
    assert "persist skipped (canary)" in error_message
    # Clause appended AFTER the canary message — ordering documents that the
    # ratchet substring was not edited, only suffixed.
    assert error_message.index("silent canary tripped:") < error_message.index(
        "persist skipped (canary)"
    )


def test_ratchet_substring_survives_truncation_worst_case():
    """CTK-116 review-fold #2 — the substring contract must hold at the
    PERSISTED layer, not just in memory. db.finish_scraper_run truncates
    error_message[:1000]; on a combined matcher+canary run the matcher
    clause precedes the canary clause, so an unbounded matcher exception
    string could push 'silent canary tripped:' past the cut and silently
    exclude the run from get_7d_median_seen's ratchet (review finding #1).
    Drives the REAL run.py construction: one 'new' decision whose matcher
    raises a 5,000-char exception, canary tripping — then mirrors db.py's
    [:1000] slice and asserts the ratchet substring survives. Fails if the
    run.py [:200] bound on matcher_error_first is ever removed."""
    _, _, finish_spy, _ = _run_orchestrator(
        n_items=3, median_seen=1000.0,
        n_new=1, matcher_exc=ValueError("x" * 5000),
    )
    args = finish_spy.call_args.args
    status, error_message = args[2], args[4]
    assert status == "failed"  # canary supersedes the matcher-partial signal
    assert "matcher exception(s)" in error_message  # matcher clause present, ahead of canary
    persisted = error_message[:1000]  # mirror db.finish_scraper_run's bound (db.py)
    assert "silent canary tripped:" in persisted
    assert "persist skipped (canary)" in persisted


# ---------------------------------------------------------------------------
# D-1 false-kill guard — clean run persists exactly as before
# ---------------------------------------------------------------------------


def test_clean_run_still_persists():
    """250 items vs 7d-median 1000 → threshold 200 → 250 >= 200 → canary
    silent. persist_phase_a invoked once, status='success', exit 0,
    finish_phase_b reached. Guards against the D-1 gate accidentally
    inverting and starving clean runs."""
    exit_code, persist_spy, finish_spy, phase_b_spy = _run_orchestrator(
        n_items=250, median_seen=1000.0,
    )
    assert exit_code == 0
    persist_spy.assert_called_once()
    phase_b_spy.assert_called_once()
    args = finish_spy.call_args.args
    assert args[2] == "success"
    assert args[3] is None  # no error_class
    assert args[5].seen == 250


# ---------------------------------------------------------------------------
# D-2 — Phase A atomicity wrap
# ---------------------------------------------------------------------------


def _mock_conn_for_phase_a(n_upserts: int):
    """Mock psycopg connection for direct persist_phase_a calls. The
    transaction + cursor context managers must return falsy from __exit__
    (MagicMock's default truthy return would swallow exceptions — the
    opposite of the loud-failure posture under test)."""
    conn = mock.MagicMock()
    conn.transaction.return_value.__exit__.return_value = False
    cur = mock.MagicMock()
    cur.fetchone.side_effect = [
        {"id": 1000 + i, "product_url": f"https://topshelfaquatics.example/products/c-{i}"}
        for i in range(n_upserts)
    ]
    conn.cursor.return_value.__enter__.return_value = cur
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cur


def _new_decisions(n: int) -> list[ItemDecision]:
    return [
        ItemDecision(
            item=_make_item(f"https://topshelfaquatics.example/products/c-{i}"),
            decision="new",
        )
        for i in range(n)
    ]


def test_persist_phase_a_enters_transaction():
    """All Phase A writes execute inside conn.transaction(). Asserts the
    context was entered AND entered before the first cursor open — the
    writes-inside-the-boundary proxy that doesn't require a live DB."""
    conn, cur = _mock_conn_for_phase_a(n_upserts=2)
    decisions = _new_decisions(2)

    mirror_queue = persist_phase_a(conn, VENDOR_ROW, decisions, {}, run_id=99)

    conn.transaction.assert_called_once()
    assert cur.execute.call_count >= 2  # 2 upserts at minimum
    # Ordering: transaction opened before any cursor — writes sit inside.
    call_names = [c[0] for c in conn.mock_calls]
    assert call_names.index("transaction") < call_names.index("cursor")
    assert mirror_queue == []  # hotlink strategy → no Phase B queue


def test_persist_phase_a_mid_write_exception_propagates_through_transaction():
    """/review-plan note #2 — transaction-entered assert over mocked
    rollback. Inject an exception mid-upsert-loop: it must PROPAGATE (loud
    failure, no swallow) and the transaction context's __exit__ must see it
    (real psycopg translates that into ROLLBACK → zero rows visible). The
    zero-rows-visible claim itself is the C2 verify-pass's job against the
    live DB; mocks only prove the boundary placement."""
    conn, cur = _mock_conn_for_phase_a(n_upserts=3)
    cur.execute.side_effect = [None, RuntimeError("boom mid-upsert")]
    # First execute succeeds (fetchone consumed), second raises mid-loop.
    cur.fetchone.side_effect = None
    cur.fetchone.return_value = {
        "id": 1000,
        "product_url": "https://topshelfaquatics.example/products/c-0",
    }
    decisions = _new_decisions(3)

    raised = False
    try:
        persist_phase_a(conn, VENDOR_ROW, decisions, {}, run_id=99)
    except RuntimeError:
        raised = True
    assert raised, "mid-write exception must propagate (no swallow)"

    conn.transaction.assert_called_once()
    exit_args = conn.transaction.return_value.__exit__.call_args.args
    assert exit_args[0] is RuntimeError  # __exit__ saw the exception → psycopg rolls back


def test_persist_phase_a_empty_decisions_no_writes():
    """Zero decisions: the transaction still opens (cheap; keeps the code
    path single-shape) but no cursor is ever requested — no writes."""
    conn, cur = _mock_conn_for_phase_a(n_upserts=0)
    mirror_queue = persist_phase_a(conn, VENDOR_ROW, [], {}, run_id=99)
    assert mirror_queue == []
    cur.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Main — runnable as `python -m scrapers.tests.test_canary_gates_persist`
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    tests = [
        test_canary_trip_skips_persist_phase_a,
        test_canary_trip_counters_flow_to_finish,
        test_canary_trip_error_message_substrings,
        test_ratchet_substring_survives_truncation_worst_case,
        test_clean_run_still_persists,
        test_persist_phase_a_enters_transaction,
        test_persist_phase_a_mid_write_exception_propagates_through_transaction,
        test_persist_phase_a_empty_decisions_no_writes,
    ]
    failures = []
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:  # noqa: BLE001
            failures.append(t.__name__)
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - len(failures)}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
