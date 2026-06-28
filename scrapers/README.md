# CoralTicker scrapers

Per-vendor scrapers, the shared Shopify/BigCommerce parse layer, the named-coral
matcher, and the test suite. Data plane is Neon Postgres via `scrapers/common/db.py`
(see the repo `CLAUDE.md` "Database access" section).

## Adding a vendor

A new vendor is **config + fixture**, not a fresh clone. The boilerplate was
consolidated in CTK-208 — use the shared pieces; do NOT copy a sibling file.

1. **YAML** — add `scrapers/vendors/<vendor>.yaml` (platform, base_url,
   scrape_method, `category_filter`, optional `auction_detection`, etc.). Mirror an
   existing same-platform vendor's structure, not its contents.

2. **Scraper** — most Shopify/BigCommerce vendors need no per-vendor Python: the
   shared `scrapers/common/parse_shopify.py` (or `parse_bigcommerce.py`) driven by
   the YAML covers them. Add a vendor module only for a genuinely bespoke platform.

3. **Parse-test** — write it as a `VendorParseConfig` against
   `scrapers/tests/vendor_parse_harness.py`. **Do NOT clone a sibling test file.**
   The harness already provides `_load_fixture`, the `_keep`/`_normalize`/
   `_tag_denylist_norm` production-call wrappers, `_by_title`, the pytest fixture
   shim, the script-mode `main()` runner, and the two common tests
   (`html_hash_first_product_keys` sentinel + CTK-115 `yaml_mirror_parity`). Your
   file = a `CONFIG`, the locked fixture, and that vendor's own regression tests.
   See `test_reefundertheroof_parse.py` / `test_coralstop_parse.py` for the shape.

   - The `yaml_mirror_parity` config is fully parameterized: set
     `expected_filter_keys` (the YAML category_filter key-set) and
     `expected_absent_axes` (axes that must NOT appear). A vendor WITH a real
     `product_type_allowlist` adopts the harness by setting these — it never edits
     the harness.
   - Run pre-flight category coverage (`preflight_category_coverage.py`, 10% NULL
     threshold) so new-vendor corals don't fall to NULL and vanish from the type
     filters.

4. **Migration** — add the SQL as `supabase/migrations/00NN_<name>.sql` and apply it
   with the shared runner. **Do NOT clone `apply_migration_00NN.py`** (those one-offs
   were deleted in CTK-208):

   ```bash
   python -m scripts.apply_migration <NN> \
       --expect-vendor '{"slug":"<vendor>","id":<id>,"platform":"shopify","active":true}'
   ```

   - `--expect-vendor '<JSON>'` runs the common declarative vendor-row verify (the
     JSON must carry a `slug`; every key is asserted equal on the `vendors` row).
   - `--drop "<SQL>"` runs DROP statements before the body so a `CREATE FUNCTION`
     migration is re-runnable.
   - For a guarantee richer than a vendor-row match that can only be checked against
     the live post-apply DB, add a `verify_<NN>(conn)` hook in
     `scripts/migration_verify.py`. Behavioral guarantees checkable WITHOUT a live
     DB (function row-shapes, parser/classifier behavior) belong in `scrapers/tests/`
     instead, so they run in CI.

   A migration committed + apply-script in git does NOT mean it ran against prod —
   apply it explicitly and confirm the verify passes.

## Running tests

```bash
# Whole suite (live-DB tests skip cleanly with no NEON_DATABASE_URL):
pytest scrapers/tests/

# CI shape — deselect the live-DB tests:
pytest scrapers/tests/ -m "not requires_db"

# A single parse-test in script mode:
python -m scrapers.tests.test_<vendor>_parse
```

Live-DB tests are marked `requires_db` and resolve their `conn` / `vendor` /
`coral_alpha` / `coral_beta` fixtures from `scrapers/tests/conftest.py`. With no
`NEON_DATABASE_URL` they SKIP (not error); with `.env` present they run against the
isolated `_ctk*_test` vendors.
