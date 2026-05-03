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

**Scope.** Triggers when the response carries findings, recommendations, multiple options, or a hand-off to another role. **Out of scope:** working agents (`/architect`, `/frontend-engineer`, `/copy-writer`, `/designer`), pure logging (`/log-results`), short replies (one-paragraph answers, single-question responses).

The block exists so future-Jon at 11pm can scan to the end, copy-paste the directive into the next agent, and act without re-reading the response. **No further commentary after the paste-ready block(s) — the close IS the close.**

## Hard rules (compliance)

- Personal laptop only. Never work laptop.
- Personal email only. Never work email.
- Personal time only. Log hours in `.claude/time-log.md`.
- No AURA/STScI tools, subscriptions, or credentials anywhere.
- COI gate: Phase 1+ engineering blocked until written COI clearance lands. (Phase 0 Track A in `.claude/reef-project-plan.md`.)

## When in doubt

If a slash command fits the work, use it. If not, read the source-of-truth files and proceed in the project's voice. Don't invent state — the plan's checkboxes and the ticket index are authoritative.
