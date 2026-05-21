// §3.3 <AccentDot>
// Renders the literal forest #1B5E20 bullet character (U+25CF).
// Forest jobs 3 (wishlist-match) + 5 (scraper-status) per branding-guide.md §"Color system".
// No color prop; variant is exhaustive against the brand-guide jobs.

type AccentDotVariant = 'wishlist-match' | 'scraper-status';

interface AccentDotProps {
  variant: AccentDotVariant;
  'aria-label': string;
}

export function AccentDot({ variant, ...rest }: AccentDotProps) {
  return (
    <span
      className="text-forest"
      aria-label={rest['aria-label']}
      data-variant={variant}
      role="img"
    >
      ●
    </span>
  );
}
