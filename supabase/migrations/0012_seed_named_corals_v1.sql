-- 0012_seed_named_corals_v1.sql
-- CTK-029 v1 Phase 3 cold-start matcher backfill — Half A2 (seed-load)
-- Inserts the top-20 demand-ranked named corals from
-- `.claude/research/named-coral-launch-seed.md` (CTK-029 v1 A1 dossier 2026-05-25).
--
-- Per architecture-v1.md:
--   #47 — slug NOT NULL UNIQUE, immutable post-insert; error-on-collision-and-curate
--          (no ON CONFLICT — bare INSERT; if a re-apply hits the unique index,
--           the migration errors loudly and the curator picks an override).
--   #20 — requires_vendor_prefix=true means the matcher rejects bare-title matches;
--          set true for entries where the bare canonical name is genuinely ambiguous
--          AND the originator prefix is the disambiguator.
--   #23 — originator_prefix lives in `scrapers/vendors/<slug>.yaml`, not the DB.
--   #65 — apply via `scrapers.common.db.get_conn` direct cursor.execute().
--
-- Slug derivation: lowercase + unaccent + whitespace-to-hyphen (kebab), internal
-- hyphens preserved (Jack-O-Lantern → jack-o-lantern). lib/slug.ts not yet built;
-- hand-derived here per #47 build-time-immutability spec — slugs are permanent.
--
-- Normalized_name derivation: lowercase + unaccent + whitespace-collapse
-- per `scrapers/common/normalize.py` `normalize_title()` shape (decision #18 vendor
-- prefix preserved). Internal hyphens preserved to match normalize_title behavior.
--
-- Apply: `python scripts/apply_migration.py 0012` (or canonical #65 path) —
-- verify normalized_name parity via the companion verification step in CTK-029
-- v1 A2 before ratifying commit.

BEGIN;

INSERT INTO named_corals (
    canonical_name,
    normalized_name,
    slug,
    origin_vendor,
    coral_type,
    genus,
    category,
    requires_vendor_prefix,
    approx_price_min,
    approx_price_max,
    notes,
    source_urls
) VALUES
-- 1 — composite 54.73
('Battlecorals PC Rainbow', 'battlecorals pc rainbow', 'battlecorals-pc-rainbow',
 'Battlecorals', 'sps', 'Acropora', 1, false,
 200, 600,
 'Red stag with orange inner body and blue rim. Battlecorals signature.',
 ARRAY['https://battlecorals.com/products/pro-corals-rainbow-acro']),

-- 2 — composite 53.59
('JF Burning Banana Stylocoeniella', 'jf burning banana stylocoeniella', 'jf-burning-banana-stylocoeniella',
 'JF', 'sps', 'Stylocoeniella', 1, false,
 80, 250,
 'Also known as Sunset Stylo. Stylocoeniella is a rare genus.',
 ARRAY['https://vividaquariums.com/products/jf-burning-banana-stylocoeniella-coral',
       'https://reefbuilders.com/2014/11/17/top-10-signature-corals-jason-fox/']),

-- 3 — composite 52.78 — COLLISION GUARD: bare "Dragon Soul" also = Dragon Soul Favia
('WWC Dragon Soul Torch', 'wwc dragon soul torch', 'wwc-dragon-soul-torch',
 'WWC', 'lps', 'Euphyllia', 1, true,
 200, 800,
 'Per-head pricing. Alias cluster: Hellfire / Indo Gold / 24k reportedly same coral under vendor rebranding. Bare "Dragon Soul" collides with Dragon Soul Favia — vendor prefix required for matcher disambiguation.',
 ARRAY['https://worldwidecorals.com/products/wwc-dragon-soul-torch-36281',
       'https://tidalgardens.com/stock-dragons-soul-torch.html']),

-- 4 — composite 50.94
('TSA Bill Murray Acropora', 'tsa bill murray acropora', 'tsa-bill-murray-acropora',
 'TSA', 'sps', 'Acropora', 1, false,
 100, 300,
 'TSA signature lineage.',
 ARRAY['https://topshelfaquatics.com/products/tsa-bill-murray-acropora-coral-1020-03']),

-- 5 — composite 50.79 — Cat 2 (community canonical, no originator prefix)
('Magician Zoanthid', 'magician zoanthid', 'magician-zoanthid',
 'community/canonical', 'zoa', 'Zoanthus gigantus', 2, false,
 30, 100,
 'Per-polyp pricing. Blue sparkle center. Category lives between zoa and paly per Tidal Gardens. Community canonical — no single originator vendor.',
 ARRAY['https://tidalgardens.com/stock-magician-zoanthids.html',
       'https://topshelfaquatics.com/products/wwc-magician-zoanthids-coral']),

-- 6 — composite 50.39 — HEAVY RELABEL GUARD: WWC originator, "WD" without prefix often not real
('WWC Walt Disney Acropora', 'wwc walt disney acropora', 'wwc-walt-disney-acropora',
 'WWC', 'sps', 'Acropora', 1, true,
 200, 800,
 'Green base, red corallites, yellow polyps, blue tips. Heavy relabel problem at third parties; "WD tenuis" without WWC prefix is often not the real piece. Vendor prefix required for matcher disambiguation.',
 ARRAY['https://reeftankadvisor.com/walt-disney-acropora/',
       'https://tidalgardens.com/stock-walt-disney-acropora-tenuis.html']),

-- 7 — composite 49.59 — COLLISION GUARD: bare "Jack O Lantern" also matches a Fungia (cross-type)
('JF Jack-O-Lantern Leptoseris', 'jf jack-o-lantern leptoseris', 'jf-jack-o-lantern-leptoseris',
 'JF', 'lps', 'Leptoseris', 1, true,
 35, 150,
 'Orange base, green eyes. One of JF most-replicated pieces. Bare "Jack O Lantern" also matches a Fungia (cross-type collision); vendor prefix required for matcher disambiguation.',
 ARRAY['https://jasonfoxsignaturecorals.com/products/lps-06',
       'https://reefbuilders.com/2014/11/17/top-10-signature-corals-jason-fox/']),

-- 8 — composite 47.63
('JF Raja Rampage Chalice', 'jf raja rampage chalice', 'jf-raja-rampage-chalice',
 'JF', 'chalice', 'Mycedium', 1, false,
 100, 400,
 'JF most iconic chalice.',
 ARRAY['https://jasonfoxsignaturecorals.com/products/ch-86']),

-- 9 — composite 45.04
('JF Foxflame', 'jf foxflame', 'jf-foxflame',
 'JF', 'sps', 'Acropora', 1, false,
 150, 400,
 'Pink body, yellow tips. Reef Builders top-10.',
 ARRAY['https://reefbuilders.com/2014/11/17/top-10-signature-corals-jason-fox/',
       'https://topshelfaquatics.com/products/jf-fox-flame-acropora-coral-1']),

-- 10 — composite 43.08
('Tyree Pink Lemonade', 'tyree pink lemonade', 'tyree-pink-lemonade',
 'Tyree/Reeffarmers', 'sps', 'Acropora', 1, false,
 80, 300,
 'Classic LE. Lime green branches, pink polyps.',
 ARRAY['https://vividaquariums.com/products/tyree-pink-lemonade-acropora-coral-1',
       'https://cultivatedreef.com/product/item-125/']),

-- 11 — composite 42.81
('JF Slow Burn Monti', 'jf slow burn monti', 'jf-slow-burn-monti',
 'JF', 'sps', 'Montipora', 1, false,
 100, 300,
 'Green fluorescent-protein-heavy monti per Reef Builders top-10.',
 ARRAY['https://reefbuilders.com/2014/11/17/top-10-signature-corals-jason-fox/']),

-- 12 — composite 40.59
('WWC Sunkist Bounce Mushroom', 'wwc sunkist bounce mushroom', 'wwc-sunkist-bounce-mushroom',
 'WWC', 'mushroom', 'Rhodactis', 1, false,
 300, 1500,
 'Orange bubbles on dark blue/green base. Propagated 10+ years at WWC.',
 ARRAY['https://worldwidecorals.com/products/wwc-sunkist-bounce-mushroom-9348',
       'https://vividaquariums.com/products/wwc-sunkist-bounce-mushroom-coral-2']),

-- 13 — composite 40.27
('JF Homewrecker', 'jf homewrecker', 'jf-homewrecker',
 'JF', 'sps', 'Acropora', 1, false,
 200, 660,
 'JF hero piece (tenuis). Widely dropshipped — listed at 8+ storefronts. Lookalike listings common; matcher confidence flag relies on lineage signals.',
 ARRAY['https://jasonfoxsignaturecorals.com/',
       'https://topshelfaquatics.com/products/jf-homewrecker-tenuis-acropora-coral-57xec_a5-041626',
       'https://www.reef2reef.com/forums/jason-fox-signature-corals.433/']),

-- 14 — composite 38.83
('TSA Garf Bonsai Acropora', 'tsa garf bonsai acropora', 'tsa-garf-bonsai-acropora',
 'TSA', 'sps', 'Acropora', 1, false,
 80, 300,
 'Deep blue/purple with green tips. Originally GARF-lineage cultivated by TSA.',
 ARRAY['https://topshelfaquatics.com/product/garf-bonsai/']),

-- 15 — composite 37.61 — COLLISION GUARD: bare "Fruity Pebbles" also = JF Fruity Pebbles Montipora (cross-vendor cross-genus)
('TSA Fruity Pebbles Acropora', 'tsa fruity pebbles acropora', 'tsa-fruity-pebbles-acropora',
 'TSA', 'sps', 'Acropora', 1, true,
 100, 400,
 'TSA most-known piece; parent of "TSA Fruity Splice" genetic morph. Bare "Fruity Pebbles" collides with JF Fruity Pebbles Montipora (cross-vendor cross-genus); vendor prefix required for matcher disambiguation.',
 ARRAY['https://topshelfaquatics.com/product/tsa-fruity-pebbles/',
       'https://worldwidecorals.com/products/tsa-fruity-pebbles-acropora']),

-- 16 — composite 36.91 — Cat 2 (community canonical)
('Utter Chaos Zoanthid', 'utter chaos zoanthid', 'utter-chaos-zoanthid',
 'community/canonical', 'zoa', 'Zoanthus gigantus', 2, false,
 30, 100,
 'Per-polyp pricing. Purple base, yellow/green swirls, orange skirts. Community canonical. Bare "Utter Chaos" also matches a chalice — zoa coral_type filter disambiguates at matcher cascade.',
 ARRAY['https://tidalgardens.com/stock-utter-chaos-zoanthids.html',
       'https://topshelfaquatics.com/products/utter-chaos-zoanthids-coral-cto']),

-- 17 — composite 36.72
('WWC OG Bounce Mushroom', 'wwc og bounce mushroom', 'wwc-og-bounce-mushroom',
 'WWC', 'mushroom', 'Rhodactis', 1, false,
 500, 3000,
 'The original bounce. Each WWC bounce variant is SKU-distinct. Mother-colony pieces top-end.',
 ARRAY['https://worldwidecorals.com/products/wwc-og-bounce-mushroom-coral',
       'https://www.reef2reef.com/threads/wwc-og-bounce-biohazard-bounce-brass-monkey-exosphere-high-end-bounce-mushrooms.1067758/']),

-- 18 — composite 36.36 — Cat 2 (community canonical)
('Gorilla Nipple Zoa', 'gorilla nipple zoa', 'gorilla-nipple-zoa',
 'community/canonical', 'zoa', 'Zoanthus/Palythoa', 2, false,
 20, 80,
 'Per-polyp pricing. Teal/orange; distinctive raised-polyp shape. Community canonical.',
 ARRAY['https://topshelfaquatics.com/products/gorilla-nipples-zoanthids-coral-sjzoa_c5_020823',
       'https://www.jlaquatics.com/gorilla-nipple-zoa.html']),

-- 19 — composite 35.05 — Cat 2 (multi-lineage trade name; promoted into top-20 per Jon ratification 2026-05-25)
('TSA Strawberry Shortcake Acropora', 'tsa strawberry shortcake acropora', 'tsa-strawberry-shortcake-acropora',
 'TSA', 'sps', 'Acropora', 2, true,
 100, 350,
 '"Strawberry Shortcake" (microclados) is now a generic trade name; TSA lineage is one of several (UC Strawberry Shortcake OG is the other main lineage). Vendor prefix required for matcher disambiguation.',
 ARRAY['https://topshelfaquatics.com/products/tsa-strawberry-shortcake-acropora-coral-almost-wysiwyg',
       'https://www.reefbum.com/sps/sps-deep-dive-strawberry-shortcake/']),

-- 20 — composite 31.00 — promoted into top-20 per Jon rescue ratification 2026-05-25 (DB-thin, R2R-strong)
('ORA Red Planet Acropora', 'ora red planet acropora', 'ora-red-planet-acropora',
 'ORA', 'sps', 'Acropora', 1, true,
 50, 200,
 'Aquacultured by ORA (hyacinthus). Tabling with red/pink corallites, metallic green base. ASD Red Planet is a separate ASD-grown lineage; vendor prefix required for matcher disambiguation against ASD subset.',
 ARRAY['https://www.orafarm.com/product/red-planet/',
       'https://battlecorals.com/products/red-planet',
       'https://www.reefbum.com/sps/sps-deep-dive-ora-red-planet/']);

COMMIT;

-- Verification (run after apply):
--   SELECT COUNT(*) FROM named_corals WHERE active = true;  -- expect 20
--   SELECT slug, canonical_name, category, requires_vendor_prefix
--     FROM named_corals ORDER BY id;
--   SELECT canonical_name FROM named_corals
--     WHERE normalized_name != lower(canonical_name);  -- spot-check unaccent
