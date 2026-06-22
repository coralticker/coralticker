-- CTK-162 §scope-c — `named_corals.lore` text column.
--
-- The editorial "lore hook" beat of the /guides two-beat coral entry (CTK-162
-- D-4 Variant B): one sourced, personal-voice sentence per coral that leads the
-- entry before the live market line. Read out of the DB via getNamedCoralBySlug
-- (lib/queries/named-corals.ts) — the shared per-coral query that already backs
-- /coral/[slug] and now the /guides reference block.
--
-- Nullable, no default, no backfill. Population is editorial and lands
-- separately (per-coral lore is hand-written from the verified roster + fact
-- sheet, not derived) — most rows stay NULL until a guide references the coral,
-- and the consumer treats NULL as "no lore yet" (the entry renders its market
-- line without a hook). A DEFAULT would fabricate empty editorial content.
--
-- Forward-safe additive: a NULLABLE ADD COLUMN with no default is a
-- metadata-only catalog change on PG11+ (no row rewrite, no lock escalation
-- against active readers/scrapers) — same posture as 0024's `pages_fetched`.
--
-- Apply ordering (Tier-1A): this migration MUST land on live Neon BEFORE the
-- getNamedCoralBySlug SELECT-widen deploys. The widened SELECT references
-- `lore`; if the column is absent the query 500s on every /coral/[slug] hit.
-- Migration-apply-pre-push (genus, the sibling field in that SELECT-widen, is
-- already live and so carries no ordering gate — lore is the gated one).
--
-- Idempotent per the migration convention: `ADD COLUMN IF NOT EXISTS` no-ops on
-- re-run.

ALTER TABLE named_corals
  ADD COLUMN IF NOT EXISTS lore text;

COMMENT ON COLUMN named_corals.lore IS
  'CTK-162 editorial lore hook. One sourced personal-voice sentence per coral, the lead beat of the /guides two-beat entry (D-4 Variant B). Read via getNamedCoralBySlug. Nullable, no default; population is editorial and hand-written per referenced coral — NULL means no lore yet (consumer renders the market line without a hook). NOT the operator-facing `notes` field (seed metadata).';
