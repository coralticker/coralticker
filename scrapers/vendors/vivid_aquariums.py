"""Vivid Aquariums — Phase 2 scraper #8 (CTK-086 Session 2).

Vendor: https://vividaquariums.com (Shopify, hourly cadence per arch §2.7
decision #15 + 0017_add_vivid_aquariums_vendor.sql, vendor_id=8). Canoga
Park CA established WYSIWYG vendor per .claude/research/phase-1.5-vendor-
scan.md §9 ("new WYSIWYG daily"); 1840-product steady-state catalog at
2026-05-27 — largest Phase 2 catalog observed to date (vs. UC=524,
Battlecorals=499, JF=452).

robots.txt (checked 2026-05-27 per arch §2.5): explicit "# Shopify
storefront. Public product, collection, page, blog, policy, cart, and
localized HTML is crawlable." preamble. Standard Shopify Allow / Disallow
shape. UCP/MCP endpoint at /api/ucp/mcp + agents.md guidance — honors
agent-aware Shopify storefront posture. Honors arch §2.5 polite-scraper
hygiene posture.

Five-signal Shopify confirmation pre-flight (vendor-scan false-positive
precedent invariant per CTK-085 Session 1c AquaSD-split-to-CTK-090): all
clean. Documented in vivid_aquariums.yaml products_path block.

Vivid title-shape findings (full 1840-product walk 2026-05-27):

  (A) Vivid self-prefix bearing: "Vivid's X" possessive form is the
      observed house-piece prefix (e.g., "Vivid's Bounce Chalice Coral",
      "Vivid's Red Velvet Alveopora Coral", "Vivid's Cotton Candy Lord
      Acan Coral", "Vivid's Salted Agave Zoanthids", "Vivid's Aquaman
      Branching Cyphastrea Decadia Coral"). Distinct from prior Phase 2
      vendors' shapes (Battlecorals 0% self-prefix bare-TitleCase, UC dual
      'UC X' + 'Unique Corals X', JF 60% 'JF X'). Vivid's possessive
      shape is unique to date.

  (B) originator_prefix=null per CTK-024 PE precedent. Seed-list
      (.claude/research/named-coral-seed-list.md) has ZERO Vivid-attributed
      canonical entries — Vivid appears only as a dropshipper/distributor
      for JF / WWC / Tyree / AquaSD lineages. With no "Vivid X" canonical
      entries to synthesize against, matcher §3.4 stage 3 synthesis is a
      no-op for Vivid pieces. Vivid's own "Vivid's X" house lineages land
      lineage_flag='unknown' at parse time.

  (C) Cross-vendor propagation: 2-4 char ALL-CAPS prefix shape catches
      cross-vendor lineages — JF, WWC, TGC, ASD, ORA, TSA prefixes
      observed (e.g., "TGC Cherry Bomb Tenuis Acropora Coral", "JF
      Spellbound Cyphastrea Coral", "WWC Bizarro Cyphastrea", "JF Bling
      Bling Cyphastrea Coral"). Matcher §3.4 stages 1-2 catch these
      directly via canonical-exact / canonical-prefix IF the seed-list
      has the right cross-vendor canonical entries; no special parse-
      layer config.

  (D) infer_lineage_flag fires on 2-4 char ALL-CAPS-prefix titles — cross-
      vendor lineages fire 'vendor-named'. Vivid's own "Vivid's X"
      possessive shape does NOT fire (mixed case, possessive apostrophe,
      not ALL-CAPS-prefix shape) — lands 'unknown'. Bare-TitleCase pieces
      (e.g., "Pink Floyd Acropora Coral", "Superbird Acropora Coral",
      "Cofefe Acropora Coral") also land 'unknown'.

Catalog-shape note: Vivid's product_type carries bucket-shape granularity
('WYSIWYG Coral' / 'Corals and Inverts' / 'Invert' / 'Saltwater Fish' /
'Dry Goods' / etc.), distinct from Battlecorals' taxonomic-genus shape
(~70 entries) and UC's structural-class shape (CORAL / Drygoods variants).
8 distinct product_types observed; two-bucket coral allowlist ('WYSIWYG
Coral' 1323 + 'Corals and Inverts' 395). All 50 actual inverts live in
the dedicated 'Invert' product_type bucket — cleanly excluded by allowlist
miss. The 'Corals and Inverts' bucket NAME admits inverts but the 2026-
05-27 walk surfaced ZERO inverts in that bucket; F1 belt-and-suspenders
tag_denylist is a defensive moat against hypothetical future re-curation.

F1 belt-and-suspenders tag_denylist values revised at Session 2 open per
/lead-backend ratification 2026-05-27 — empirical full-catalog tag-shape
sweep surfaced plurality mismatch with /review-plan F1 fold's singular-
form prescription. Revised to Vivid's empirical invert-bucket canon.
High-order intent preserved; literal values corrected.

Anemone/clam-keep fold (CTK-087 sibling 2026-05-28): 'Anemones' + 'Clams'
dropped from the denylist (10 tags: Clean Up Crew / Crabs / Cucumbers /
Lobsters / Nudibranch / Shrimp / Snails / Starfish / Tube Worms / Urchin).
The fleet keeps anemones + clams (PE/TSA/AquaSD + CTK-087 Tidal Gardens;
seed-list carries named BTAs), so a future named BTA re-filed under the
allowlisted 'Corals and Inverts' bucket must not be denied. Vivid's current
anemone/clam stock all sits in the non-allowlisted 'Invert' bucket, so the
removal is forward-protective only (0 newly-kept at 2026-05-28 dry-run).

First-variant SKU non-null rate spot-check 2026-05-27: empirical sample
across page 1 (250 products) shows 100% non-null first-variant SKU rate
— matches PE / WWC / JF / Battlecorals / UC pattern. parse_shopify's
first-non-empty-SKU pick at _normalize_product gracefully falls back to
null vendor_sku when all variants lack SKUs.

Pure /products.json shakedown — no per-vendor overrides. All scrape
behavior inherited from scrapers.common.parse_shopify via the shared
run.py orchestrator. The vendors row + scrapers/vendors/vivid_aquariums.yaml
carry all config; this module is the hook point where vendor-specific
overrides would land if Vivid's site shape ever requires them (none
anticipated for the canonical Shopify shakedown).

Test fixture regen path (CTK-024/025/026/027/Battlecorals/UC convention):
  curl -sS "https://vividaquariums.com/products.json?limit=250" \\
    -H "User-Agent: <Chrome UA per scrapers/common/http.py>" \\
    > /tmp/vivid_page1.json
  # Pick 2-3 representative products by title per F3 fold (NOT one-per-
  # product-type): one 'WYSIWYG Coral' bucket coral with Vivid's-possessive
  # self-prefix (e.g., Vivid's Salted Agave Zoanthids), one 'Corals and
  # Inverts' bucket cross-vendor lineage (e.g., JF Spellbound Cyphastrea
  # Coral or WWC Bizarro Cyphastrea), one 'Invert' bucket reject case
  # (e.g., Peppermint Shrimp — exercises product_type_allowlist miss).
  # Write to scrapers/tests/fixtures/vivid_aquariums/products.sample.json.
  # See test_vivid_aquariums_parse.py for the expected shape assertions
  # the fixture must continue to satisfy.
"""
