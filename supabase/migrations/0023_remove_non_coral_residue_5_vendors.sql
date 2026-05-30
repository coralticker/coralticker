-- CTK-095 Axis 2 — remove non-coral residue across 5 vendors.
--
-- Scope-extended from JF-only at orient (per /lead-backend Axis 2 brief
-- 2026-05-30) after fleet-sweep raw_title regex audit surfaced PE + TSA + BC
-- re-leaks alongside the original JF + UC targets. 5 vendors total, all
-- correctness Tier 1A on /vendor/[slug] + /new renders.
--
-- Root-cause split:
--   PE — 3 rows. All STALE legacy from pre-CTK-037 era (intake allowlist now
--        excludes PT='Inverts' / 'Live Food'; rows survived CTK-041 v1+v2
--        intersection DELETE).
--   TSA — 28 rows. Mix of (a) stale stickers/hoodies/T-shirts inserted at
--         TSA cold-start 2026-05-07 pre-CTK-037 allowlist; (b) clams + fish
--         that current TSA tag_denylist doesn't catch (Wrasse / Hawkfish /
--         Gudgeon / Goby / Clam tags not in v1+v2 denylist). YAML extends in
--         lock-step with this migration.
--   JF — 1 row. WHITE AND YELLOW LIP HYBRID TANG (PT='WYSIWYG' in allowlist;
--        tags=['WYSIWYG'] only — no tag mechanism catches title-only fish
--        leak). Structural gap: title-keyword filter mechanism would close;
--        flagged for /lead-backend follow-up.
--   BC — 5 rows. Gift Cards + 4 Tee Shirts (PT='' empty-bucket allowlist-
--        included per CTK-085 Session 2 Q-8 (a); tags=[] empty — no tag
--        mechanism catches). Structural gap: same as JF; flagged.
--   UC — 115 rows. Equipment / supplements / lighting; mostly STALE legacy
--        from UC cold-start 2026-05-25 (CTK-085 Session 3 lock). PT='DRYGOODS'
--        / 'Drygoods' / 'Panta Rhei' all excluded at intake by current
--        allowlist; cold-start rows stuck in_stock=true awaiting CTK-094
--        cohort-comparison-OOS ship.
--
-- Residual cleanup is intersection-DELETE shape (per CTK-041 lean (a)); R2
-- orphans natural-decay per project_catalog_rotation_natural_recovery memory.
-- FK price_history.listing_id has ON DELETE CASCADE — child rows clean
-- automatically.
--
-- IDs locked via scripts/_axis2_final_ids.py Python-regex audit
-- 2026-05-30 + manual exclusion-guard correction for 2 false-keeps
-- (TSA 35353 Holy Grail Torch Coral Sticker excluded by `\bcoral\b`; UC 67246
-- Cyanoacrylate Coral Frag Glue excluded by `cyanoacrylate`).

-- vendor_id=1 pacific_east — 3 rows
DELETE FROM vendor_listings WHERE vendor_id = 1 AND id IN (
    50948, 51924, 51930
);

-- vendor_id=3 tsa — 28 rows
DELETE FROM vendor_listings WHERE vendor_id = 3 AND id IN (
    35353, 35354, 35356, 35367, 35399, 36570, 36639, 36923, 37385, 37403,
    38475, 38509, 38510, 38511, 51296, 51297, 51298, 51299, 51300, 51301,
    51302, 51303, 51304, 51305, 51306, 51307, 66782, 66783
);

-- vendor_id=4 jf — 1 row
DELETE FROM vendor_listings WHERE vendor_id = 4 AND id IN (
    73807
);

-- vendor_id=5 battlecorals — 5 rows
DELETE FROM vendor_listings WHERE vendor_id = 5 AND id IN (
    67586, 67589, 67590, 67593, 67688
);

-- vendor_id=6 unique_corals — 115 rows
DELETE FROM vendor_listings WHERE vendor_id = 6 AND id IN (
    67096, 67107, 67118, 67120, 67121, 67122, 67123, 67124, 67125, 67131,
    67132, 67133, 67135, 67136, 67137, 67138, 67140, 67141, 67142, 67143,
    67144, 67145, 67146, 67147, 67148, 67149, 67151, 67153, 67154, 67155,
    67156, 67180, 67181, 67186, 67188, 67228, 67231, 67232, 67246, 67267,
    67268, 67276, 67278, 67279, 67280, 67281, 67282, 67293, 67294, 67295,
    67296, 67297, 67299, 67300, 67301, 67302, 67303, 67306, 67308, 67309,
    67311, 67312, 67313, 67314, 67315, 67316, 67317, 67318, 67319, 67321,
    67328, 67345, 67346, 67347, 67348, 67349, 67377, 67383, 67389, 67390,
    67391, 67413, 67416, 67418, 67420, 67428, 67434, 67437, 67438, 67439,
    67440, 67441, 67442, 67443, 67452, 67453, 67454, 67455, 67456, 67457,
    67459, 67460, 67461, 67462, 67464, 67465, 67466, 67467, 67468, 67469,
    67470, 67471, 67472, 67475, 67476
);
