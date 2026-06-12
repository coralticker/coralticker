// Neutral primitive. Cream/ink palette. `name` + `aria-label` required
// (Server Action FormData key + a11y floor). `type` discriminator widens at
// the second consumer.
//
// 'box' is the original chrome; 'nav-underline' (branding-guide §"Mono
// uppercase register" <SearchBar> entry): 2px `line` underline at rest; focus
// flips to 1px full ink with pb compensated 4px->5px so total box height is
// constant. No box/chip/fill, transparent over the nav's surface, mono text
// at nav-chrome size, placeholder `mute` letterspaced (the literal-uppercase
// placeholder string is the caller's job — CSS text-transform doesn't
// reliably reach placeholders), no forest in any state, bounded width so the
// input wraps as a unit on narrow viewports. WebKit's native search-cancel
// decoration is suppressed — it would be the only non-bare control chrome in
// the system. `line`/`mute` per the served-neutral re-spec (branding-guide
// §"Served-neutral re-spec") — these served tones are authoritative and
// deliberately diverge from the nominal spec: the nominal ink/NN forms never
// compiled, so don't revert to them.

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
  box: 'block w-full px-3 py-2 bg-cream text-ink border border-line font-sans text-sm placeholder:text-mute focus:outline-none focus:border-ink disabled:opacity-50',
  'nav-underline':
    'w-56 max-w-full py-1 bg-transparent text-ink border-0 border-b-2 border-line font-mono text-xs placeholder:text-mute placeholder:tracking-[0.08em] focus:outline-none focus:border-b focus:border-ink focus:pb-[5px] appearance-none [&::-webkit-search-cancel-button]:appearance-none disabled:opacity-50',
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
