"""scrapers/tests/test_parse_shopify_pagination_terminator.py — CTK-208: the missing
multi-page fetch_and_parse pagination-terminator test (graduated open-item, folded at
harness root).

parse_shopify.fetch_and_parse walks pages 1..max_pages and stops on one of three
terminators, none of which had a unit test before this file:
  1. EMPTY page   — a page whose "products" list is [] breaks the loop (the page is
     still counted in pages_fetched — it was fetched successfully).
  2. SHORT page   — a page with fewer than page_size rows is the last page; break
     (spares one wasted round-trip).
  3. max_pages    — the `for page in range(1, max_pages + 1)` cap halts a feed that
     never returns a short/empty page (runaway guard).

The terminator decisions key off the RAW page length, before the category filter, so
these tests drop every row with a title_denylist (the rows never reach
_normalize_product) and assert purely on how many pages were requested + pages_fetched.
http.fetch is swapped for a canned multi-page responder — no network, no DB.

Runnable as:
  python -m scrapers.tests.test_parse_shopify_pagination_terminator
"""

from __future__ import annotations

import json
import sys
import traceback
from contextlib import contextmanager

from scrapers.common import http, parse_shopify

PAGE_SIZE = 250

# Drop every fake row at the filter so _normalize_product is never exercised — the
# terminator logic runs on the raw page length regardless of filtering.
_CONFIG = {
    "base_url": "https://pagination.test",
    "page_size": PAGE_SIZE,
    "max_pages": 30,
    "request_delay_sec": 0,
    "category_filter": {"title_denylist": ["Coral"]},
}


def _fake_product(i: int) -> dict:
    return {"title": f"Coral {i}", "product_type": "", "tags": [], "handle": f"p{i}"}


@contextmanager
def _patched_fetch(page_sizes: list[int]):
    """Swap http.fetch with a canned responder. page_sizes[k] = the row count to
    return for page k+1; a request beyond the list returns an empty page. Yields the
    list of page numbers actually requested so a test can assert the loop stopped."""
    requested: list[int] = []

    def fake_fetch(url, request_delay_sec=2.0):
        page = int(url.rsplit("page=", 1)[1])
        requested.append(page)
        n = page_sizes[page - 1] if page - 1 < len(page_sizes) else 0
        body = json.dumps({"products": [_fake_product(i) for i in range(n)]}).encode("utf-8")
        return http.FetchResult(body=body, status_code=200, error_class=None, error_message=None)

    original = http.fetch
    http.fetch = fake_fetch
    try:
        yield requested
    finally:
        http.fetch = original


def test_empty_page_terminates():
    """A full page followed by an empty page stops the walk — page 3 is never
    requested, and the empty page IS counted in pages_fetched (it was fetched)."""
    with _patched_fetch([PAGE_SIZE, 0]) as requested:
        result = parse_shopify.fetch_and_parse(_CONFIG)
    assert requested == [1, 2], f"expected pages [1, 2] requested, got {requested}"
    assert result.pages_fetched == 2, f"empty page should still count: pages_fetched={result.pages_fetched}"
    assert result.items == [], "all rows are title-denylisted — no items expected"


def test_empty_first_page_terminates():
    """A store whose very first page is empty (no products at all) terminates cleanly
    after one fetch — page 1 is counted in pages_fetched, page 2 is never requested,
    and no items are produced (the empty-catalog / down-store shape)."""
    with _patched_fetch([0]) as requested:
        result = parse_shopify.fetch_and_parse(_CONFIG)
    assert requested == [1], f"empty first page must stop after page 1, got {requested}"
    assert result.pages_fetched == 1, f"empty page 1 still counts as fetched: pages_fetched={result.pages_fetched}"
    assert result.items == [], "empty first page yields no items"


def test_short_page_terminates():
    """A single short page (< page_size) is the last page — only page 1 is fetched."""
    with _patched_fetch([PAGE_SIZE - 1]) as requested:
        result = parse_shopify.fetch_and_parse(_CONFIG)
    assert requested == [1], f"short first page must stop the walk, got {requested}"
    assert result.pages_fetched == 1, f"pages_fetched={result.pages_fetched}"


def test_full_pages_continue_until_short():
    """Two full pages then a short page — the walk fetches all three and stops."""
    with _patched_fetch([PAGE_SIZE, PAGE_SIZE, PAGE_SIZE - 5]) as requested:
        result = parse_shopify.fetch_and_parse(_CONFIG)
    assert requested == [1, 2, 3], f"expected pages [1, 2, 3], got {requested}"
    assert result.pages_fetched == 3, f"pages_fetched={result.pages_fetched}"


def test_max_pages_cap_halts_runaway():
    """A feed that always returns a full page must still halt at max_pages — never
    fetch page max_pages+1 (the runaway guard)."""
    cfg = {**_CONFIG, "max_pages": 3}
    with _patched_fetch([PAGE_SIZE] * 10) as requested:
        result = parse_shopify.fetch_and_parse(cfg)
    assert requested == [1, 2, 3], f"max_pages=3 must cap the walk at 3, got {requested}"
    assert result.pages_fetched == 3, f"pages_fetched={result.pages_fetched}"


def main() -> int:
    tests = [
        test_empty_page_terminates,
        test_empty_first_page_terminates,
        test_short_page_terminates,
        test_full_pages_continue_until_short,
        test_max_pages_cap_halts_runaway,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
