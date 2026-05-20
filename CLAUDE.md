# CoralTicker — Claude project orientation

**What it is:** A coral-drop aggregator + alert service for reef hobbyists. Solo project by Jon (data engineer by day) at 3-5 hrs/week. Free aggregator tier + $15/mo Hunter tier. Full plan in `.claude/reef-project-plan.md`.

**Current state:** Phase 1 active as of 2026-05-02. Architecture v1 (CTK-001) complete; first scraper (Pacific East, Shopify-based) being scoped. COI gate cleared via silence-path: disclosed 2026-04-23, no further response, invoked at day 9 per plan §Phase 0 Track A footnote.

## Source-of-truth files

| File | What it holds |
|---|---|
| `.claude/reef-project-plan.md` | Product plan, phase plan, market sizing, vendor list, compliance posture |
| `.claude/architecture-v1.md` | Technical design (data model, scrapers, matcher, notifier, deploy, observability) |
| `.claude/branding-guide.md` | Voice principles + before/after copy examples |
| `.claude/plans/tickets/index.md` | All CTK tickets — status, phase, gate |
| `.claude/plans/tickets/CTK-XXX/{plan,results}.md` | Per-ticket plan + session log |
| `.claude/coordination-invariants.md` | Cross-CTK constraints; `/reef-lead` + `/lead-frontend` enforce per scope (channel parity, brand-mockup gate, shared-primitive rules) |
| `.claude/open-items.md` | Cross-CTK / cross-session hygiene items below CTK threshold; `/reef-lead` reads + maintains. Items graduate to CTKs when scope grows past ~5-min hygiene. |
| `.claude/commands/` + `.claude/commands-guide.md` | Slash commands and how to use them |
| `.claude/journal/YYYY-MM-DD-*.md` | Session journals |
| `.claude/research/*.md` | Vendor scans, market research, named-coral seed list |
| `.claude/time-log.md` | COI compliance evidence (personal time only) |

## Repo layout — two-repo split

`.claude/` is its own **private** git repo, separate from the **public** `coralticker` repo. The public repo's `.gitignore:1` excludes `.claude/` so session work — ticket scaffolding, plan.md / results.md / journal entries, brand + architecture sources — stays private. Both repos live side-by-side under the same working directory and version-control independently:

- **Public** — `app/`, `components/`, `lib/`, `scrapers/`, `CLAUDE.md`, etc. Pushed to GitHub `coralticker/coralticker`.
- **Private `.claude/`** — orientation docs, ticket history, brand + architecture sources, session journals. Synced via its own remote.

Implication for commit directives: `.claude/` paths can't enter a public-repo commit alongside code changes — `git add -f` would override the gitignore but persistently auto-track those files in the public repo, defeating the split. Bundle directives must separate code from `.claude/` artifacts (the `.claude/` work commits in the private repo as a separate operation). See memory `feedback_paste_directive_gitignored_artifacts.md`.

## Voice

Grounded, dry, specific, first-person singular. No SaaS hype. See `.claude/branding-guide.md` for principles + before/after examples. Match `.claude/reef-project-plan.md`'s register.

**No emojis in artifacts (architecture-v1.md, branding-guide.md, site.md, copy drafts, design files, plan files, results.md, journal entries, the project plan itself).** One carve-out: slash commands MAY use a constrained scan-aid emoji vocabulary in their *conversational* output. Vocabulary: 🟥 (blocker / blocking-now), 🟧 (moderate / weigh-in), ⚠️ (minor / sliding / flag-for-review), ✅ (clean / locked / no finding). Each command's source defines its exact vocabulary and scope. Carve-out scope:

- **Review commands** — `/lead-review`, `/review-plan`, `/review-results`, `/coo-review` — full vocabulary on findings.
- **Synthesis commands** — `/reef-lead`, `/lead-architect`, `/lead-frontend`, `/lead-backend`, `/brand-manager` — full vocabulary on Blocking-now / Parking-lot / Focus-close.
- **Working agents** — `/architect`, `/frontend-engineer`, `/backend-engineer`, `/copy-writer`, `/designer` — only ✅ (at-a-glance header) and ⚠️ (Flags-for-/lead-X pull-out section) in checkpoint output. No 🟥 / 🟧 — they're builders, not deciders.
- **Logging / journal commands** — `/log-results`, `/journal` — no emoji carve-out; they write into artifacts.

Emojis stay out of every artifact regardless of which command produced it.

## Slash commands

Six project commands cover design and project management. Quick reference in `.claude/commands-guide.md`. Source of truth: each `.md` file in `.claude/commands/`.

Default for "what should I do next?" → `/reef-lead` (whole-project state) or `/lead-architect trajectory` (architecture-specific).

## Lead-role response shape

Lead/synthesis roles (`/lead-architect`, `/lead-frontend`, `/lead-backend`, `/lead-review`, `/brand-manager`, `/reef-lead`) close every dense response with a **Forward Action block** — visually separated by `---`, fixed shape, nothing after it:

```
---
**Blocking now:** [one verb-phrase] — [why this is the unblock]
**Parking lot:**
- [item] — [trigger that re-surfaces it]
- [item] — [trigger]
```

If nothing is blocking: `**Blocking now:** (nothing — proceed).` Skip the parking lot when there are no deferred items.

**Paste-ready next-agent prompts.** When a Forward Action item names a clear next agent (`/brand-manager`, `/copy-writer`, `/architect`, `/designer`, `/frontend-engineer`, `/backend-engineer`, `/lead-architect`, `/lead-frontend`, `/lead-backend`, etc.), include a paste-ready directive *below* the Forward Action block, demarcated per the existing paste-directive convention:

```
### Paste to /<target>

---
[self-contained directive — next agent can act on it cold]
---
```

The bar: would future-Jon copy-paste this into another agent? If yes, write it paste-ready — don't just gesture at "tell /brand-manager about X." If no (Jon-decision yes/no, hand-edit, memory save, scheduling call), skip.

**Scope.** Triggers when the response carries findings, recommendations, multiple options, or a hand-off to another role. **Out of scope:** working agents (`/architect`, `/frontend-engineer`, `/copy-writer`, `/designer`), pure logging (`/log-results`), short replies (one-paragraph answers, single-question responses), conversational pushback (Jon correcting the prior recommendation, expressing frustration, or naming an override input — match the moment with prose, not template).

The block exists so future-Jon at 11pm can scan to the end, copy-paste the directive into the next agent, and act without re-reading the response. **No further commentary after the paste-ready block(s) — the close IS the close.**

### Mode discipline

These rules apply to lead/synthesis roles (same scope as the Forward Action block) and override the default-to-density posture when they conflict.

**Mode resets per turn.** Mode isn't sticky. Re-detect from Jon's most recent prompt; don't carry the prior turn's mode forward. Density burns Jon's context — match the shape of his prompt. A clarifying question after a dense synthesis turn gets a short prose answer. Pushback after a recommendation gets acknowledgment plus a switch, not more recommendation.

**Premise-contradiction = re-derive, not re-defend.** When Jon names a constraint or preference that contradicts a load-bearing premise of a prior in-session recommendation, the recommendation is no longer valid. Re-derive from the new premise set; don't restate the conclusion with the new input appended. The cue is the contradiction itself — frustration is a second signal, premise-shift is the first. Example: a recommendation built on a cost-vs-time tradeoff stops applying the moment Jon says "cost is a hard ceiling." (Memory: `feedback_override_means_stop_relitigating.md`.)

**Independent judgment until decision; execute-support after.** Lead roles earn keep by being the second voice that catches things from a different angle *while a recommendation is forming*. Once Jon has chosen, switch to execute-support — list blockers for the path he named, route the work, surface honest tradeoffs once for the record, then stop pitching the rejected option. "Don't be a yes-man" applies pre-decision; "don't re-litigate" applies post.

**Routing isn't a relitigation tool.** When Jon has named an override himself, "route to /lead-X for re-evaluation" is delay dressed up as procedure unless he's asking for the re-eval. Execute on the override; let the affected lane absorb the decision retroactively via the normal results.md / decision-register channels.

## Hard rules (compliance)

- Personal laptop only. Never work laptop.
- Personal email only. Never work email.
- Personal time only. Log hours in `.claude/time-log.md`.
- No AURA/STScI tools, subscriptions, or credentials anywhere.
- COI gate: Phase 1+ engineering blocked until written COI clearance lands. (Phase 0 Track A in `.claude/reef-project-plan.md`.)

**Agent vs. Jon-facing scope.** The first three rules (laptop / email / time / log-hours) are Jon-facing self-discipline — agents do **not** echo, cite, or remind Jon about these in outputs. Don't tack "Personal time only per CLAUDE.md hard rules" onto results.md entries, review trailers, commit-step bullets, or any other artifact; it adds zero information and reads as babysitting. The AURA/STScI and COI rules are real agent constraints: flag any plan that proposes AURA tooling, and treat the COI gate as a hard block on Phase 1+ work.

## Database access

Hosted Postgres is a Neon project (post-CTK-043 cutover 2026-05-16; see architecture-v1.md decision register row #65). Agents query it from Python via psycopg + `.env`-loaded `NEON_DATABASE_URL`:

```python
# Canonical agent path — small script in scripts/ using scrapers/common/db.py:
from scrapers.common.db import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ...")
        print(cur.fetchall())
```

See `scripts/diag_neon_data_plane.py` (landed CTK-043 2026-05-17) for the canonical script shape.

Alternative paths (Jon-side, not agent-default):
- `psql "$NEON_DATABASE_URL"` — after `. .env`; connection-string-in-shell-history hazard, weigh against query density.
- Neon Console SQL editor at neon.tech — GUI; no shell exposure; no agent path.

`scrapers/common/db.py` auto-loads `NEON_DATABASE_URL` from `.env` via `python-dotenv` (`load_dotenv()` at module import per L44). Agents never read the connection string into shell. Auth is whatever credentials the URL embeds; rotation is dashboard-side at neon.tech.

Not MCP, not the deprecated supabase-py PostgREST client (retired per CTK-043 cut-1). Direct psycopg via `scrapers/common/db.py` is the canonical Python-side path; raw `psql "$NEON_DATABASE_URL" -c` works for one-off shell queries but requires sourcing `.env` into shell first (connection-string-in-history hazard per the alternative-paths note above) — prefer the Python path.

### Python scrapers + psycopg — `.env` loader

When running Python code that touches the DB (scrapers, tests, ad-hoc scripts), `scrapers/common/db.py` calls `load_dotenv()` at module import. Values flow from `.env` at repo root (gitignored) into `os.environ` automatically — no per-script `$env:` setup. To set up locally: copy `.env.example` (committed template) to `.env` and fill in the real `NEON_DATABASE_URL` from the Neon dashboard. CI uses GitHub Actions secrets via workflow YAML `env:` block; never reads `.env`.

To run a Python script that touches the DB:

```bash
python -m scrapers.tests.test_fetch_existing_listings_pagination
```

Auth is transparent. `python-dotenv` is in `scrapers/requirements.txt`.

Neon Postgres auth is the credential embedded in `NEON_DATABASE_URL`; rotation is dashboard-side at neon.tech. No application-layer API keys for the data plane (post-CTK-043; the Supabase `sb_secret_*` / `sb_publishable_*` key format from CTK-033 is retired with the data-plane cutover — historical context in CTK-033 results.md). Phase 4 auth provider (row #24) may reintroduce application-layer API keys.

### Secret-handling discipline

Never run commands that dump secret VALUES to stdout — `supabase projects api-keys`, `cat .env`, `gh secret list --json` with values, `aws secretsmanager get-secret-value`, etc. Bash/PowerShell tool output lands in the conversation transcript; secrets in transcript = leak per architecture-v1.md §6.3 rotate-on-suspected-leak. To stash a new secret to GitHub Actions or similar: have Jon run `gh secret set --body "<value>"` in his own terminal so the value never crosses the agent surface; verify via timestamp on `gh secret list` (no values shown). See `feedback_secret_stash_jon_terminal.md` memory for the full discipline.

## When in doubt

If a slash command fits the work, use it. If not, read the source-of-truth files and proceed in the project's voice. Don't invent state — the plan's checkboxes and the ticket index are authoritative.
