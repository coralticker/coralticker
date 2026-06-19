-- Per-channel referral attribution on email_signups: a second, independent axis
-- from `source`.
--
-- `source` (ENUM) records WHICH SURFACE the form was submitted from (homepage,
-- footer, coral_page, ...). `referrer_channel` records WHICH CHANNEL drove the
-- visit here (ig, r2r, discord, reddit) — captured first-touch from a ?ref= param
-- via middleware cookie, read at the server action. The two are orthogonal: a
-- homepage signup can arrive via the IG bio link, so source=homepage +
-- referrer_channel=ig is the normal case, not a conflict.
--
-- Plain nullable text, NOT an ENUM (unlike source). The channel set churns faster
-- than the surface set — new campaigns/platforms come and go — so validation lives
-- in the app-layer allowlist (types/email-signups REFERRER_CHANNELS). Adding a
-- channel is then a one-line code change, not a migration + ALTER TYPE round-trip.
--
-- NULL means "no channel signal" (organic / direct). We store no 'direct' literal:
-- reporting derives it with COALESCE(referrer_channel, 'direct') so the column
-- never carries a sentinel that could be confused with a real channel.
--
-- IF NOT EXISTS so the apply script is re-run-safe (house convention).

ALTER TABLE email_signups
    ADD COLUMN IF NOT EXISTS referrer_channel text;

COMMENT ON COLUMN email_signups.referrer_channel IS
  'First-touch referral channel (ig/r2r/discord/reddit), captured from ?ref= via the ct_ref cookie. Independent of source (which records the form surface). NULL = organic/direct; no ''direct'' literal is stored (reporting derives it via COALESCE). Validation is the app-layer allowlist, not a DB ENUM, so the channel set churns without migrations.';
