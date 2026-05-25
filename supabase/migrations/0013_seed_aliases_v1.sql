-- 0013_seed_aliases_v1.sql
-- CTK-030 v1 Half B B1 — cross-vendor aliases seed (auto-link rows only).
-- Source: `.claude/research/named-coral-launch-seed.md`
--   §"Aliases (CTK-030 v1 A1 — ratified 2026-05-25)" appendix.
--   41 aliases across 17 of 20 named_corals. IDs 6 / 15 / 19 carry zero
--   per CTK-030 v1 A1 ratification (heavy-relabel FP risk on 6,
--   cross-genus collision on 15, cluster-tier on 19). Two descriptive
--   ID=3 rows ('indo gold torch' + '24k torch') dropped post-B3 per
--   /lead-architect ruling 2026-05-25 — FP-prone origin/color
--   descriptors; the 4 remaining flagged-ID rows are specific
--   trade-names (Hellfire / Dragon Soul cluster + 2 ID=20 ORA Red
--   Planet variants).
--
-- Per architecture-v1.md:
--   #5  / §1.8 — aliases table, two row shapes enforced by CHECK; this
--                migration seeds shape 1 only (auto-link, named_coral_id IS
--                NOT NULL, cluster_label IS NULL). Cluster-flag rows
--                (shape 2) deferred to v2 or a dedicated CTK.
--   §1.8 L505 — alias_text is "lowercased, normalized (matches
--                normalized_title form)". Strings below are pre-computed
--                via `scrapers.common.normalize.normalize_title()` so the
--                migration is self-contained at apply time.
--   §3.4 stage 4 — alias_hit cascade path. /lead-architect ruling
--                2026-05-25 (CTK-030 v1 B3 Q-A): aliases bypass
--                `requires_vendor_prefix=true`. Implemented at
--                `scrapers/common/matcher.py` stage-4 loop bundled in
--                this commit — stage-4 alias auto-link skips the §3.5
--                cat-2 guard. Stages 1/2/3/6 still apply the guard for
--                canonical-name lookups per decision #20. B3 re-fire
--                verified post-edit (bare "hellfire torch" /
--                "dragon's soul torch" → ID=3; bare "red planet
--                acropora" → ID=20; bare cat-2 canonical still rejects).
--   #65 — apply via `scrapers.common.db.get_conn` direct cursor.execute()
--          over the full SQL text; the BEGIN/COMMIT below carries
--          server-side tx control under psycopg autocommit=True.
--
-- Idempotency: partial UNIQUE index `ux_al_text_coral` (step i) plus
-- ON CONFLICT (alias_text, named_coral_id) WHERE named_coral_id IS NOT
-- NULL DO NOTHING (step ii). The ON CONFLICT predicate matches the
-- partial-index predicate verbatim; mismatch errors loudly at apply.
--
-- Pre-apply sanity (run before this migration fires):
--   SELECT COUNT(*) FROM aliases;   -- expect 0; non-zero means a prior
--                                   -- CTK seeded aliases out-of-band.

BEGIN;

-- Step (i): first uniqueness guard on aliases. Pre-v1 the table had only
-- non-unique indexes (architecture-v1.md §1.8 L520-521). Partial predicate
-- respects the §1.8 CHECK row-shape split: cluster-flag rows
-- (named_coral_id IS NULL) stay outside this guard so the same alias_text
-- can appear once as auto-link and once as cluster-flag without violating
-- uniqueness.

CREATE UNIQUE INDEX ux_al_text_coral
  ON aliases (alias_text, named_coral_id)
  WHERE named_coral_id IS NOT NULL;

-- Step (ii): 41 auto-link rows from the CTK-030 v1 A1 ratified dossier
-- (post /lead-architect 2026-05-25 ID=3 drop — see header).

INSERT INTO aliases (alias_text, named_coral_id, match_behavior) VALUES
-- named_coral_id=1 — Battlecorals PC Rainbow
('pc rainbow acropora',                       1, 'auto-link'),
('pro corals rainbow acro',                   1, 'auto-link'),
('pc rainbow acro',                           1, 'auto-link'),
-- named_coral_id=2 — JF Burning Banana Stylocoeniella
('sunset stylo',                              2, 'auto-link'),
-- named_coral_id=3 — WWC Dragon Soul Torch (requires_vendor_prefix=true; aliases bypass per /lead-architect Path A 2026-05-25)
-- Two descriptive rows ('indo gold torch', '24k torch') dropped post-B3 — FP-prone origin/color descriptors per /lead-architect ruling.
('hellfire torch',                            3, 'auto-link'),
('dragon''s soul torch',                      3, 'auto-link'),
-- named_coral_id=4 — TSA Bill Murray Acropora
('bill murray acropora',                      4, 'auto-link'),
-- named_coral_id=5 — Magician Zoanthid
('magicians',                                 5, 'auto-link'),
('magician zoa',                              5, 'auto-link'),
('wwc magician zoanthid',                     5, 'auto-link'),
-- named_coral_id=7 — JF Jack-O-Lantern Leptoseris
('jack o lantern leptoseris',                 7, 'auto-link'),
('jack-o-lantern lepto',                      7, 'auto-link'),
('jason fox jack-o-lantern leptoseris',       7, 'auto-link'),
-- named_coral_id=8 — JF Raja Rampage Chalice
('raja rampage chalice',                      8, 'auto-link'),
('jason fox raja rampage chalice',            8, 'auto-link'),
-- named_coral_id=9 — JF Foxflame
('jf fox flame',                              9, 'auto-link'),
('fox flame acropora',                        9, 'auto-link'),
('jason fox fox flame acropora',              9, 'auto-link'),
-- named_coral_id=10 — Tyree Pink Lemonade
('pink lemonade acropora',                   10, 'auto-link'),
('lime green acro',                          10, 'auto-link'),
-- named_coral_id=11 — JF Slow Burn Monti
('slow burn montipora',                      11, 'auto-link'),
('ecc love shack',                           11, 'auto-link'),
('jason fox slow burn montipora',            11, 'auto-link'),
-- named_coral_id=12 — WWC Sunkist Bounce Mushroom
('sunkist bounce',                           12, 'auto-link'),
('sunkist bounce mushroom',                  12, 'auto-link'),
-- named_coral_id=13 — JF Homewrecker
('homewrecker acropora',                     13, 'auto-link'),
('homewrecker tenuis',                       13, 'auto-link'),
('homewrecker acropora tenuis',              13, 'auto-link'),
-- named_coral_id=14 — TSA Garf Bonsai Acropora
('garf bonsai acropora',                     14, 'auto-link'),
('garf bonsai',                              14, 'auto-link'),
('og garf bonsai',                           14, 'auto-link'),
-- named_coral_id=16 — Utter Chaos Zoanthid
('utter chaos zoa',                          16, 'auto-link'),
('utter chaos zoanthids',                    16, 'auto-link'),
('utter chaos palythoa',                     16, 'auto-link'),
-- named_coral_id=17 — WWC OG Bounce Mushroom
('og bounce mushroom',                       17, 'auto-link'),
('og bounce',                                17, 'auto-link'),
('wwc og bounce',                            17, 'auto-link'),
-- named_coral_id=18 — Gorilla Nipple Zoa
('gorilla nipples',                          18, 'auto-link'),
('gorilla nipple zoanthid',                  18, 'auto-link'),
-- named_coral_id=20 — ORA Red Planet Acropora (requires_vendor_prefix=true; aliases bypass per /lead-architect Path A 2026-05-25)
('red planet acropora',                      20, 'auto-link'),
('red planet acro',                          20, 'auto-link')
ON CONFLICT (alias_text, named_coral_id) WHERE named_coral_id IS NOT NULL DO NOTHING;

COMMIT;

-- Verification (run after apply):
--   SELECT COUNT(*) FROM aliases WHERE named_coral_id BETWEEN 1 AND 20;
--     -- expect 41.
--   SELECT named_coral_id, COUNT(*) FROM aliases
--     WHERE named_coral_id BETWEEN 1 AND 20
--     GROUP BY named_coral_id ORDER BY named_coral_id;
--     -- expected distribution:
--     --   1:3  2:1  3:2  4:1  5:3  7:3  8:2  9:3  10:2  11:3
--     --   12:2 13:3 14:3 16:3 17:3 18:2 20:2
--     -- IDs 6, 15, 19 carry zero per A1 ratification.

-- Rollback (two-step; index survives DELETE):
--   DELETE FROM aliases WHERE named_coral_id BETWEEN 1 AND 20;
--   DROP INDEX ux_al_text_coral;
