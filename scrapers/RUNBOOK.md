# Scrapers Runbook

Incident fingerprint table + resolution-path-of-record for Phase 1 scraper failures. Future-Jon at 11pm greps this file for the failure-string fingerprint, reads the disposition path, applies the resolution.

Sibling to `architecture-v1.md` §6 (monitorable surfaces); covers operational failure modes the architecture doesn't enumerate at design-time. Each entry captures the failure surface, the disposition path that isolated the load-bearing vector, the resolution-path-of-record, and a triage shortcut for future instances.

## Fingerprint index

| Failure string | First observed | Load-bearing vector | Resolution path | Anchor |
|---|---|---|---|---|
| `fetch error (other): other: unknown failure` | 2026-05-25 | GH Actions runner-IP-network degradation (transient, runner-pool-level) | Runbook-only; no scraper-side fix | [§1 below](#fetch-error-other-other-unknown-failure) |

---

## `fetch error (other): other: unknown failure`

**Source.** `scrapers/common/run.py` L209-215 — `parse_shopify.FetchError` catch-clause when `e.error_class` falls outside `{http_429, http_5xx, network}`, status flips to `failed`, `error_class="other"`. The substring `other: unknown failure` originates at `scrapers/common/http.py` L108 — the retry-loop fallthrough when all 3 attempts returned HTTP responses that didn't classify as 200 / 429 / 5xx / network-error / block. DNS / TCP / TLS errors classify as `network` at L72, not `other` at L108. The precise per-attempt status pattern (3x 403-without-WAF-body, or a mix) is not recoverable from scraper_runs row data — only the final summary survives.

**Fast-path triage (single command).** Pattern-match against the load-bearing signal (cross-vendor + cross-cadence simultaneous failure):

```
gh api 'repos/coralticker/coralticker/actions/runs?per_page=20&event=schedule' --jq '[.workflow_runs[] | select(.created_at >= "<window-open>") | {wf: .name, status, conclusion, created_at}] | sort_by(.created_at)'
```

If ≥2 distinct workflows fail with identical fingerprint within a 4-hour window, vector (d) runner-IP-network is the operative shape; skip to "Future-instance triage" step 3.

**Observed instance 2026-05-25.** 12 of 15 schedule fires failed (80% failure rate) across all 4 Phase 1 vendors (WWC + TSA + JF + PE) between 04:10 and 14:36 UTC. Last failure cluster: TSA 14:34:28Z + WWC 14:36:55Z. Self-resolved without intervention; first clean fires at JF 16:56:27Z + TSA 16:59:20Z + WWC 17:00:23Z (3 workflows clean within 4 min of each other; 2h 20m gap from last failure). PE is daily; verified clean at scraper_runs.id=313 via local re-run at 17:06 UTC (`status=success`, 4735 listings_seen).

**Vector disposition (per CTK-091 Session 2 2026-05-25).**

| Vector | Disposition | Probe |
|---|---|---|
| (a) Vendor-side platform-API change | RULED OUT | Per-vendor `curl /products.json` HTTP 200 + standard Shopify shape across PE/WWC/TSA/JF. Cross-vendor co-recovery within 4 min rules out independent platform-API change. |
| (b) Network-side outage (CDN/edge) | RULED OUT | `cloudflarestatus.com/api/v2/incidents.json` window-filter empty (only Workers Builds, post-window). Shopify storefronts are Fastly-fronted; CF irrelevant for the documented vendor set. |
| (c) Scraper-side `http.py` regression | RULED OUT | `git log --since=<previous-cron-cycle> -- scrapers/common/` empty. Local re-run `.venv/bin/python -m scrapers.common.run <slug>` clean against live store. |
| (d) GH Actions backend network degradation | INCONCLUSIVE-but-load-bearing-by-elimination | `githubstatus.com/api/v2/incidents.json` window-filter empty (no Actions component incident named). Runner-IP-network sub-class load-bearing by elimination of (a)/(b)/(c) + cross-vendor self-clear pattern. GH Actions doesn't publish runner-network diagnostics; positive confirmation surface not available. |

**Resolution path of record.** Runbook-only close. No scraper-side fix — incident self-resolved at runner-pool level without code change or vendor-side change. Recurrence is GH Actions runner-pool-level and not under scraper-code control. Architecture-v1 §2.4 loud-failure invariant: failed runs recorded with classified `error_class="other"`, `listings_seen=0` on failed rows (clean abort, no partial-data persistence). §6.3 Slack `if: failure()` alert fired per failed run.

Sibling open item: `.claude/open-items.md` L53 records "GH Actions schedule degradation 2026-05-12 — `0 * * * *` top-of-hour cron silence across all hourly vendors". Same GH Actions backend, different surface (scheduling-delay vs. fetch-error). GH Actions backend operational issues recur intermittently; pattern-match against this cluster before launching deep investigation.

**Future-instance triage (60-second budget for steps 1-3).**

1. `gh api` recent-runs check (5 sec). Has the failure cluster already self-cleared since you noticed it? If newest fires per workflow are `conclusion=success`, runbook closes here — log the fingerprint instance and monitor next cycle.
2. GitHub Actions status (10 sec): `curl -s https://www.githubstatus.com/api/v2/incidents.json | jq '.incidents[] | select(.created_at >= "<window-open>") | {name, status, components: [.components[].name], created_at}'`. Named Actions-component incident overlapping window → vector (d) status-page-confirmed; wait + monitor.
3. Cloudflare status (10 sec, same shape against `cloudflarestatus.com`) — only run if failure is single-vendor and that vendor is CF-fronted (per-vendor `curl -I` `cf-ray` header check). Skip for Shopify-only vendor sets.
4. **Beyond 60s budget — escalation.** If steps 1-3 clear and failure window extends past 4 hours without self-clear (roughly 2x the 2026-05-25 precedent's 2h 20m self-clear gap), open new CTK at /reef-lead lane=/lead-backend tier=1A for active investigation. Step 2 probes: per-vendor `/products.json` HTTP-status pre-flight, local re-run via `.venv/bin/python -m scrapers.common.run <slug>`, manual `workflow_dispatch` re-fire at non-top-of-hour minute. Reference this entry as precedent context.

---

**Cite-source.** Investigation: `.claude/plans/tickets/CTK-091/` (Session 2 vector disposition + Session 3 runbook close). Architecture invariants: `.claude/architecture-v1.md` §2.4 (loud-failure semantics) + §6.3 (Slack failure alert).
