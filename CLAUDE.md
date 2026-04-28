# CoralTicker — Claude project orientation

**What it is:** A coral-drop aggregator + alert service for reef hobbyists. Solo project by Jon (data engineer by day) at 3-5 hrs/week. Free aggregator tier + $15/mo Hunter tier. Full plan in `.claude/reef-project-plan.md`.

**Current state:** Pre-implementation. Architecture being designed in `.claude/architecture-v1.md` (CTK-001, in progress). Phase 1 scrapers not yet started — gated on written COI clearance from STScI (disclosed 2026-04-23).

## Source-of-truth files

| File | What it holds |
|---|---|
| `.claude/reef-project-plan.md` | Product plan, phase plan, market sizing, vendor list, compliance posture |
| `.claude/architecture-v1.md` | Technical design (data model, scrapers, matcher, notifier, deploy, observability) |
| `.claude/branding-guide.md` | Voice principles + before/after copy examples |
| `.claude/plans/tickets/index.md` | All CTK tickets — status, phase, gate |
| `.claude/plans/tickets/CTK-XXX/{plan,results}.md` | Per-ticket plan + session log |
| `.claude/coordination-invariants.md` | Cross-CTK constraints `/reef-lead` enforces (channel parity, shared-primitive rules) |
| `.claude/commands/` + `.claude/commands-guide.md` | Slash commands and how to use them |
| `.claude/journal/YYYY-MM-DD-*.md` | Session journals |
| `.claude/research/*.md` | Vendor scans, market research, named-coral seed list |
| `.claude/time-log.md` | COI compliance evidence (personal time only) |

## Voice

Grounded, dry, specific, first-person singular. No emojis. No SaaS hype. See `.claude/branding-guide.md` for principles + before/after examples. Match `.claude/reef-project-plan.md`'s register.

## Slash commands

Six project commands cover design and project management. Quick reference in `.claude/commands-guide.md`. Source of truth: each `.md` file in `.claude/commands/`.

Default for "what should I do next?" → `/reef-lead` (whole-project state) or `/lead-architect trajectory` (architecture-specific).

## Hard rules (compliance)

- Personal laptop only. Never work laptop.
- Personal email only. Never work email.
- Personal time only. Log hours in `.claude/time-log.md`.
- No AURA/STScI tools, subscriptions, or credentials anywhere.
- COI gate: Phase 1+ engineering blocked until written COI clearance lands. (Phase 0 Track A in `.claude/reef-project-plan.md`.)

## When in doubt

If a slash command fits the work, use it. If not, read the source-of-truth files and proceed in the project's voice. Don't invent state — the plan's checkboxes and the ticket index are authoritative.
