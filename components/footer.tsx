// §3.5.4 <Footer> — every view, including Phase 4 auth-gated views
// Per branding-guide.md §"Surface boundary" + §"Wordmark + tagline lockup" footer rule:
//   - Wordmark + disclaimer line is the entire footer composition
//   - No tagline in footer (lives at hero only on hero surfaces)
//   - No "Built by Jon" on product-voice surfaces (lives on /about + R2R + Discord intros)
//   - Plex Mono lowercase / sentence case in inkFaint for the disclaimer line
//     (branding-guide.md §"Mono uppercase register" footer-chrome carve-out)
//
// `Last scrape: {timestamp}` will source from lib/queries at a later session
// (Session 1b ships lib/queries/*); v1 placeholder renders an em-dash until then.

import { Wordmark } from '@/components/ui/wordmark';

export function Footer() {
  return (
    <footer className="px-6 py-6 mt-12 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Wordmark variant="nav" />
        <span className="font-mono text-ink/60">
          Not affiliated with vendors. · Last scrape: —
        </span>
      </div>
    </footer>
  );
}
