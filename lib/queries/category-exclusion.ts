// Canonical hidden-category denylist — the categories excluded from every count /
// aggregate / feed surface. CTK-186 step 2 added 'equipment'; CTK-212 added 'invert'
// (motile inverts — shrimp / crabs / urchins / snails / nudibranchs — per Biota, the
// first vendor stocking them by design, ~15 live rows). One source for every consumer:
// the bare-/new + listings feeds (lib/queries/listings.ts), /search
// (lib/queries/search.ts), the email digest (lib/email/digest.ts), and the SQL
// content functions (kept in lockstep by supabase/migrations/0067 + the INV-07 parity
// test). Adding the next hidden category is a one-line edit HERE.
//
// DEPENDENCY-FREE LEAF BY DESIGN — no `next/*`, no `@/` imports. The digest runs in
// the bare-node `--experimental-strip-types` cron graph (scripts/run_email_digest.ts
// -> lib/email/digest.ts), which resolves no `@/` aliases and can't load the Next
// runtime. Importing this constant from lib/queries/listings.ts (where it used to live)
// would drag `next/cache` + `@/lib/db/neon` into that graph and break the cron — proven
// empirically, see memory project_bare_node_import_graph. So the canonical constant
// lives HERE, importable from both the Next bundler and the bare-node graph.
//
// NULL-SAFE consumption is MANDATORY. Reclassified None-category corals carry
// category=NULL and MUST stay visible. The set form `vl.category <> ALL(...)` drops
// NULLs on its own (NULL <> ALL -> NULL -> row excluded), so every call site guards
// with the IS NULL arm:
//   (vl.category IS NULL OR vl.category <> ALL(${EXCLUDED_CATEGORIES}::text[]))
// clam / anemone are FACET categories (user-filterable type chips) and are
// deliberately ABSENT here — they stay visible.
export const EXCLUDED_CATEGORIES = ['equipment', 'invert'] as const;
