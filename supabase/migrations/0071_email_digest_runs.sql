-- CTK-218 -- email digest idempotency guard. A per-UTC-date sent-row so a re-fire of
-- the same day's digest (a missed-cron manual re-run racing a recovered cron, or two
-- workflow_dispatches landing together) no-ops instead of double-sending to the
-- recipient list.
--
-- runEmailDigest() reads this row at entry (today's UTC-date row present -> return
-- already-sent) and writes it in the post-send success path -- sent >= 1 only,
-- immediately after Resend accepts the batch. Paired with a Resend Idempotency-Key
-- on the send itself (key = email-digest-{utc-date}), which closes the Resend-side
-- window; this row closes our re-entry window. The double-send risk is MINIMIZED,
-- not eliminated -- a crash in the gap between Resend's 200 and this row's commit
-- would let a later run re-enter, and only the Resend key (24h dedup window) catches
-- that residual.
--
-- sent-only by design: a no-recipients / no-events / dry-run day writes NO row. The
-- watchdog (scripts/email_digest_watchdog.py) keys off that absence and self-
-- disambiguates by reporting the day's qualifying-drops count in the alert.
--
-- Apply: python -m scripts.apply_migration 71
-- Verify: verify_0071 (committed != applied, feedback_migration_committed_not_applied).

CREATE TABLE IF NOT EXISTS email_digest_runs (
  sent_date  date PRIMARY KEY,
  sent_count int NOT NULL,
  sent_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE email_digest_runs IS
  'CTK-218 -- fire-once-per-UTC-date guard for the daily email digest. One row per day a real send (sent_count >= 1) completed. Read at runEmailDigest() entry (row present -> already-sent no-op); written immediately after Resend accepts the batch. No row for no-send days (no-recipients/no-events/dry-run) -- the watchdog keys off the absence.';
COMMENT ON COLUMN email_digest_runs.sent_date IS
  'UTC calendar date of the send (PRIMARY KEY -- the fire-once key). UTC, not ET: the guard answers "did we already send on this UTC day", matching the cron 13:00 UTC fire.';
COMMENT ON COLUMN email_digest_runs.sent_count IS
  'Messages handed to Resend across all batches for the day (the DigestResult.sent value).';
