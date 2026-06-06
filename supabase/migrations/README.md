# Migration apply-order rules

**Default — apply-pre-push:** the migration runs against live Neon before the commit carrying it pushes. Holds for additive and output-narrowing changes (new column, new function alongside an old one, predicate tightening) — the deployed frontend tolerates them.

**Exception — deploy-frontend-first** (0034/0035 precedents): migrations that widen or uncap reader-RPC output, or drop a signature the deployed frontend still calls, invert the order. Push + verify the frontend that tolerates the new shape FIRST, then apply, then push the migration files as their own commit. Applying first serves the new shape through the old frontend for the deploy gap (0034 would have 500'd `/deals`; 0035 would have served the full uncapped union).

When in doubt: ask what the currently-deployed frontend does with the post-apply output during the gap.
