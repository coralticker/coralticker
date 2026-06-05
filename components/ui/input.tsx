// §3.4.1 <Input> — neutral primitive
// Cream/ink palette. `name` + `aria-label` required (per §3.4.1 — Server Action
// FormData key + a11y floor). `type` discriminator widens at second consumer.
// `id` is optional — surfaced at Q-040-9 disposition (CTK-040 Session 2) per
// the "first consumer surfaces the API" pattern from <Button>'s onClick at
// Session 1b; first consumer is <SignupForm>'s <label htmlFor="signup-email">
// click-to-focus association.
//
// CTK-058: second consumer (<SearchBar>) widens `type` with 'search' and
// surfaces a `variant` discriminator per the same first-consumer-surfaces-
// the-API pattern. 'box' is the original chrome verbatim; 'nav-underline' is
// the INV-02 round-2 variant A lock (branding-guide §"Mono uppercase
// register" <SearchBar> entry, L286): 2px ink/40 underline at rest;
// focus flips to 1px full ink with pb compensated 4px->5px so total box
// height is constant (rest/focus weights superseded at Jon live-eyeball
// 2026-06-05 — 1px ink/30 rest read as nonexistent on cream; 2px full-ink
// focus too heavy; 2px /40->/60 shift imperceptible; thick-quiet rest /
// thin-sharp focus is the ratified pair) — no
// box/chip/fill, transparent over the nav's surface, mono text at nav-chrome
// size, placeholder ink/60 letterspaced (the literal-uppercase placeholder
// string is the caller's job — CSS text-transform doesn't reliably reach
// placeholders), no forest in any state, bounded width so the input wraps as
// a unit on narrow viewports. WebKit's native search-cancel decoration is
// suppressed — it would be the only non-bare control chrome in the system.

interface InputProps {
  name: string;
  type: 'email' | 'search';
  'aria-label': string;
  id?: string;
  placeholder?: string;
  required?: boolean;
  defaultValue?: string;
  disabled?: boolean;
  variant?: 'box' | 'nav-underline';
}

const VARIANT_CLASS: Record<NonNullable<InputProps['variant']>, string> = {
  box: 'block w-full px-3 py-2 bg-cream text-ink border border-ink/30 font-sans text-sm placeholder:text-ink/60 focus:outline-none focus:border-ink disabled:opacity-50',
  'nav-underline':
    'w-56 max-w-full py-1 bg-transparent text-ink border-0 border-b-2 border-ink/40 font-mono text-xs placeholder:text-ink/60 placeholder:tracking-[0.08em] focus:outline-none focus:border-b focus:border-ink focus:pb-[5px] appearance-none [&::-webkit-search-cancel-button]:appearance-none disabled:opacity-50',
};

export function Input(props: InputProps) {
  return (
    <input
      id={props.id}
      name={props.name}
      type={props.type}
      aria-label={props['aria-label']}
      placeholder={props.placeholder}
      required={props.required}
      defaultValue={props.defaultValue}
      disabled={props.disabled}
      className={VARIANT_CLASS[props.variant ?? 'box']}
    />
  );
}
