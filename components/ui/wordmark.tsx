// §3.1 <Wordmark>
// Renders `coralticker.` per branding-guide.md §"Wordmark" / §"Mark" / §"Wordmark + tagline lockup".
// coral 700 + ticker 400 + forest #1B5E20 full-stop. Lowercase locked.
// Variants 1:1 with brand-guide surface-treatment table.

type WordmarkProps =
  | { variant: 'hero'; tagline?: string }
  | { variant: 'nav' }
  | { variant: 'mark' };

export function Wordmark(props: WordmarkProps) {
  if (props.variant === 'mark') {
    return <span className="text-forest font-bold">.</span>;
  }

  const wordmark = (
    <span>
      <span className="font-bold">coral</span>
      <span className="font-normal">ticker</span>
      <span className="text-forest font-bold">.</span>
    </span>
  );

  if (props.variant === 'nav') {
    return wordmark;
  }

  // hero — left-aligned wordmark + em-dash rule + tagline per branding-guide.md
  // §"Wordmark + tagline lockup" — wordmark 1.60× tagline (CTK-052 wordmark-dominant
  // lock 2026-05-19; supersedes CTK-040 Q-2 Variant C 1.30× balance ratio), tagline
  // Plex Mono 0.08em tracking, rule spans remaining line-width.
  //
  // CTK-056 S2: responsive degradation per branding-guide.md §"Wordmark + tagline
  // lockup" L320 (locked 2026-05-20). <640px: stacked composition — wordmark row 1,
  // tagline row 2, both left-anchored, no rule (a rule on its own row reads as a
  // section divider, not the sequential-pause em-dash the motif requires).
  // ≥640px: horizontal lockup unchanged (wordmark 1.60× + spanning rule + inline
  // tagline). Wordmark 1.60× ratio honored at every viewport.
  //
  // CTK-056 S3: sm:items-baseline (not items-center) per /lead-frontend eyeball-
  // pass review-results. items-center floats tagline + 1px rule in the vertical
  // middle of the 1.60× wordmark's line-box; items-baseline aligns them to the
  // wordmark's baseline (where the forest full-stop sits) — typographic standard
  // for inline rule-with-text lockups. Mobile (flex-col) unchanged — items-baseline
  // only fires above sm: breakpoint.
  const tagline = props.tagline ?? 'Never miss the drop.';
  return (
    <span className="flex flex-col sm:flex-row sm:items-baseline gap-3 text-2xl md:text-3xl">
      <span className="text-[1.60em]">{wordmark}</span>
      <span
        aria-hidden="true"
        className="hidden sm:block h-px bg-ink flex-auto"
      />
      <span className="font-mono font-bold uppercase tracking-[0.08em]">{tagline}</span>
    </span>
  );
}
