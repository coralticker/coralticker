// No color prop; variant is exhaustive against forest's jobs (wishlist-match
// + scraper-status per branding-guide §"Color system").

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
