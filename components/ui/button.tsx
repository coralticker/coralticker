// Neutral primitive. Cream/ink palette, no forest (forest's 5 jobs don't
// include button colors). No variant prop at v1; widens via
// discriminated-union extension at the second consumer.

interface ButtonProps {
  type: 'button' | 'submit';
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  'aria-busy'?: boolean;
}

export function Button({
  type,
  children,
  disabled,
  onClick,
  'aria-busy': ariaBusy,
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      aria-busy={ariaBusy}
      className="inline-flex items-center justify-center px-4 py-2 bg-ink text-cream font-sans font-bold text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
    >
      {children}
    </button>
  );
}
