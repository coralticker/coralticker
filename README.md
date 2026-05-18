# CoralTicker

Coral-drop aggregator + alert service for reef hobbyists. Solo project — see `.claude/reef-project-plan.md` for product scope and phase plan; `.claude/architecture-v1.md` for the data model and scrapers; `.claude/site.md` for the Phase 2 frontend.

## Local development

Requires Node.js 20+ and pnpm 11+. The repo is hand-rolled (no `create-next-app` scaffold).

```bash
pnpm install
pnpm approve-builds --all
pnpm build
```

### Why `pnpm approve-builds --all` is a one-time setup step

pnpm 11 ships a build-script-approval safety feature: postinstall scripts in dependencies (which can run arbitrary code) must be explicitly approved before they run. CoralTicker's `package.json` allowlists `sharp` (Next.js image-optimization native binary) and `unrs-resolver` (ESLint resolver) under `pnpm.onlyBuiltDependencies`, but the allowlist alone doesn't approve the pending build scripts — `pnpm approve-builds --all` drains the approval queue once. After the first run, `pnpm install` and `pnpm build` exit clean with no `ERR_PNPM_IGNORED_BUILDS` advisory. CI (Vercel) re-runs the same approval flow per build environment; per-environment config isn't needed.

### Scripts

| Script | Purpose |
|---|---|
| `pnpm dev` | Next.js dev server at `http://localhost:3000`. |
| `pnpm build` | Production build (`next build`). |
| `pnpm start` | Production server (`next start`) after a successful build. |
| `pnpm lint` | ESLint via `next lint`. |
| `pnpm typecheck` | `tsc --noEmit` against the strict-mode baseline (`strict: true` + `noUncheckedIndexedAccess: true`). |

## Environment

Copy `.env.example` to `.env` at repo root and fill in `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` from the Supabase dashboard. `.env` is gitignored; CI injects the same variables via GitHub Actions secrets per workflow YAML.

## Repo layout

| Path | What lives there |
|---|---|
| `app/` | Next.js App Router routes (Phase 2 public site). |
| `components/ui/` | Brand primitives per `.claude/site.md` §3.1-§3.4 + §3.6. |
| `components/` | Compositions per `.claude/site.md` §3.5. |
| `lib/format/` | Pure-helper formatters; INV-01 channel-parity siblings consumed by web + email + Discord + push. |
| `lib/queries/` | Server-side Supabase query helpers (read-path). |
| `lib/supabase/` | Server-side Supabase client wrapper. |
| `scrapers/` | Python scrapers (Phase 1; see `.claude/architecture-v1.md` §2). |
| `.claude/` | Project plan, architecture, brand guide, site doc, tickets, slash-command sources. Working-tree-only; gitignored. |

## Tickets

Per-ticket plan + session log under `.claude/plans/tickets/CTK-XXX/`. Index at `.claude/plans/tickets/index.md`.
