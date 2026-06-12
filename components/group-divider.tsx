// The label string is caller-formatted (branding-guide §"Group dividers"
// ladder); view loops compute the boundary transition and label.

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
