-- Migration 0045 — CTK-170 Item C: ig_spotlight_picks pick-history table.
--
-- The bracket-diversity guard (scrapers/tools/ig_select.py) down-weights a price
-- band that is over-represented in the recent spotlight picks. ig_spotlight is
-- notify-only (it surfaces a skeleton to the Slack operator channel; Jon publishes
-- by hand), so nothing recorded what got selected until now. This append-only table
-- is that history: one row per surfaced pick on every non-dry-run ig_spotlight run.
--
-- The row records the SURFACED pick, not a confirmed post (human-in-the-loop; we
-- can't observe the actual publish) — an acceptable proxy for a soft down-weight
-- (CTK-170 D-1 caveat). Append-only, additive, no backfill: nothing reads history
-- that predates the table, so an empty table simply means "no recent-band signal
-- yet" (the guard contributes 0 until picks accumulate).
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS, re-runnable, no DROP, no data
-- writes. Mirrors the price_history append-only shape (0001 §1.5) — bigserial PK,
-- listing_id FK to vendor_listings ON DELETE CASCADE (a purged listing takes its
-- pick rows with it; the recent-window signal is a rolling tail, so losing old
-- rows is harmless).

CREATE TABLE IF NOT EXISTS ig_spotlight_picks (
  id           bigserial PRIMARY KEY,
  listing_id   bigint NOT NULL REFERENCES vendor_listings(id) ON DELETE CASCADE,
  band         text NOT NULL,
  selected_at  timestamptz NOT NULL DEFAULT now(),
  mode         text NOT NULL
);

COMMENT ON TABLE ig_spotlight_picks IS
  'Append-only IG-spotlight pick history (CTK-170 Item C). One row per SURFACED pick per non-dry-run ig_spotlight run — a proxy for "posted" (human-in-the-loop; D-1 caveat). Read by the bracket-diversity guard for the trailing-window band balance; never user-facing.';

COMMENT ON COLUMN ig_spotlight_picks.band IS
  'Price band at selection time (ig_select.price_band): <$150 / $150-400 / $400-800 / $800+. Stored as the label so the recent-window read is a plain GROUP BY, no re-banding against a moved edge.';

COMMENT ON COLUMN ig_spotlight_picks.mode IS
  'Selection mode the pick came from: daily | weekly-roundup. The recent-window read is mode-scoped so the daily rotation balances against daily picks.';

-- The only read pattern: trailing N picks for a mode, newest first.
CREATE INDEX IF NOT EXISTS idx_isp_mode_selected
  ON ig_spotlight_picks (mode, selected_at DESC, id DESC);
