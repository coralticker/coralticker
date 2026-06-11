// Shared 96×96 listing-row image slot — the single thumb treatment for both
// /corals (app/corals/page.tsx) and ListingRowFrame (the /new + /deals +
// /coral/[slug] + /vendor/[slug] feed/inventory rows). Visual canon locked at
// CTK-009 DR-CTK009-BG-1 #1 (/brand-manager 2026-06-11): bg-wash box,
// object-cover, NO NO-IMAGE label (branding-guide §"Row hover + image-slot
// tones" Q129-1) — a null src renders the bare wash box; the row still lists.
//
// aria-hidden = (alt === '' || !src) is the locked /lead-frontend a11y call
// (DR #1): a decorative caller passes alt="" → the slot is always hidden
// (something else carries the accessible name); a named caller passes derived
// alt text → the slot is hidden only when imageless (no alt to announce). Both
// reduce to current behavior exactly — /corals was always-hidden, ListingRowFrame
// was hidden-iff-imageless.
import Image from 'next/image';

// Shared box geometry/tone for the 96px slot. Exported so the /corals loading
// skeleton bone consumes the SAME class string (as `${THUMB_SLOT_BOX}
// animate-pulse`) — a future thumb-size or bg change propagates to both, so the
// skeleton's parity comment is structurally honored, not just asserted.
export const THUMB_SLOT_BOX = 'shrink-0 w-24 h-24 bg-wash';

export function ThumbSlot({ src, alt }: { src: string | null; alt: string }) {
  return (
    <div className={THUMB_SLOT_BOX} aria-hidden={alt === '' || !src}>
      {src ? (
        <Image
          src={src}
          alt={alt}
          width={96}
          height={96}
          sizes="96px"
          unoptimized
          className="w-24 h-24 object-cover"
        />
      ) : null}
    </div>
  );
}
