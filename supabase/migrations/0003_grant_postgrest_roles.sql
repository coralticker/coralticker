-- CTK-024 Session 7 — public-schema GRANT to PostgREST roles + default
-- privileges for future tables.
--
-- Operational consequence of disabling "Automatically expose new tables
-- and functions" at project security setup: service_role + anon +
-- authenticated need explicit GRANTs before PostgREST can access tables.
-- Currently applied only to hosted via Studio SQL editor (Session 6);
-- this migration makes the GRANT durable so fresh `supabase db reset`
-- bootstraps don't need a manual step. Idempotent (GRANT is set-not-
-- append; ALTER DEFAULT PRIVILEGES is also idempotent) per arch
-- decision #35.
--
-- service_role bypasses RLS for backend writes per arch §1.3.
-- anon + authenticated get USAGE only here; per-table SELECT grants
-- land in Phase 3 frontend tickets (CTK-009) when read paths surface.
--
-- ALTER DEFAULT PRIVILEGES captures future tables/sequences/functions
-- added in Phase 2+ migrations automatically — without this, every new
-- table would need a per-migration GRANT (recurring tax + easy to
-- forget at solo cadence). Fold it in now so default-correct holds.

-- Existing-object grants (apply to tables present at migration time).
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO service_role;

-- Future-object grants (apply to tables added by future migrations).
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO service_role;
