-- CTK-016 Leg 1 (D-1) — per-row opaque token on email_signups.
--
-- D-1 locked the token mechanism as a stored random indexed column (HMAC-
-- stateless rejected): an unsubscribe link must stay valid effectively forever
-- (CAN-SPAM >= 30-day floor, practically years), and an HMAC ties every
-- outstanding link's validity to a single app secret that can't rotate without
-- mass-breaking live links already in inboxes. A per-row token is rotation-
-- independent, individually revocable, and costs one column + one unique index.
-- One token per row serves BOTH /confirm and /unsubscribe; the route scopes the
-- purpose.
--
-- NOT NULL DEFAULT gen_random_uuid()::text is load-bearing for two reasons:
--
--   (a) Backfill in one statement. gen_random_uuid() is a VOLATILE default, so
--       PG evaluates it per-row at ADD COLUMN time (a table rewrite, not the
--       PG11 constant-default fast-path) — every existing row lands a distinct
--       non-null token without a separate UPDATE. Instant at this table's size.
--
--   (b) Live-path safety net. This applies to Neon BEFORE Leg 3 deploys. Until
--       Leg 3, app/signup/actions.ts inserts (email, source) only and mints no
--       token. Without the default, any signup landing in that window would
--       write a NULL token — an unconfirmable row on a Tier-1B surface. The
--       default keeps every row tokened through the deploy gap; Leg 3 then
--       overrides it with an app-minted crypto.randomBytes(32) value. The
--       default is retained afterward as a permanent safety net (backfill
--       values need not match the app-mint encoding — both are opaque).
--
-- gen_random_uuid() is core in Neon's PG15/16 — no pgcrypto extension needed.
-- Index is named to match idx_es_email_lower (0001_init.sql:247).
--
-- Existing rows are NOT backfilled on confirmed_at: they stay DOI-pending per
-- plan.md §1.9.1 (confirmed_at IS NULL = double-opt-in pending). This migration
-- touches token only.
--
-- IF NOT EXISTS on both statements so the apply script is re-run-safe (house
-- convention; mirrors 0036). On a second run the column/index already exist and
-- the statements are inert.

ALTER TABLE email_signups
    ADD COLUMN IF NOT EXISTS token text NOT NULL DEFAULT gen_random_uuid()::text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_es_token ON email_signups (token);

COMMENT ON COLUMN email_signups.token IS
  'Per-row opaque token; serves both /confirm and /unsubscribe (route scopes purpose). Backfilled + new-row default via gen_random_uuid()::text; Leg 3 overrides with app-minted crypto.randomBytes(32).toString(base64url). Default retained as safety net. Arch decision CTK-016 D-1.';
