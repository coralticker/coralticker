// §3.4.1 <Button> — neutral primitive
// Cream/ink palette, no forest (forest's 5 jobs don't include button colors).
// No variant prop at v1 per Decision L; widens via discriminated-union extension
// at second consumer (likely Phase 3 push-opt-in modal).
// Specced against text spec only at Session 1a; first visible surface is
// <SignupForm> at Session 1b per Gate-1 flag 3.

// onClick surfaced at Session 1b — app/error.tsx retry button is the first
// type="button" consumer per site.md §3.4.1 "first consumer surfaces the API".
// Submit consumers continue to omit it (form action target via <form action>).
//
// aria-busy surfaced at CTK-065 — <SignupForm> SubmitButton is the first
// submit-pending consumer (WCAG 2.1 §4.1.3 SR-layer announcement).

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
