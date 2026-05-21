// §3.5.7 <GroupDivider> — feed-shape day-bucket separator
//
// Forest single-pixel hairline + mono uppercase letterspaced label rendered at
// the row's Ref-field left edge + 28px above / 16px below padding. The
// composition encapsulates all four (hairline, label render, label register,
// padding). The label string is caller-formatted (per branding-guide.md
// §"Group dividers" line 260 ladder); view loops compute the boundary
// transition and label via lib/format/group-bucket.ts.

interface GroupDividerProps {
  label: string;
}

export function GroupDivider({ label }: GroupDividerProps) {
  return (
    <div
      role="separator"
      className="pt-7 pb-4"
      aria-label={label}
    >
      <div className="border-t border-forest" />
      <div aria-hidden="true" className="mt-3 font-mono text-xs uppercase tracking-[0.08em] text-ink">
        {label}
      </div>
    </div>
  );
}
