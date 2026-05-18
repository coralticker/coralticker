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
  // §"Wordmark + tagline lockup" — wordmark 1.30× tagline (Variant C lock 2026-05-18),
  // tagline Plex Mono 0.08em tracking, rule spans remaining line-width.
  const tagline = props.tagline ?? 'Never miss the drop.';
  return (
    <span className="flex w-full items-center gap-3 text-2xl md:text-3xl">
      <span className="text-[1.30em]">{wordmark}</span>
      <span
        aria-hidden="true"
        className="h-px bg-ink flex-auto"
      />
      <span className="font-mono font-bold uppercase tracking-[0.08em]">{tagline}</span>
    </span>
  );
}
