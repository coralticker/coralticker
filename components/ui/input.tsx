// §3.4.1 <Input> — neutral primitive
// Cream/ink palette. `name` + `aria-label` required (per §3.4.1 — Server Action
// FormData key + a11y floor). `type` discriminator widens at second consumer.
// `id` is optional — surfaced at Q-040-9 disposition (CTK-040 Session 2) per
// the "first consumer surfaces the API" pattern from <Button>'s onClick at
// Session 1b; first consumer is <SignupForm>'s <label htmlFor="signup-email">
// click-to-focus association.

interface InputProps {
  name: string;
  type: 'email';
  'aria-label': string;
  id?: string;
  placeholder?: string;
  required?: boolean;
  defaultValue?: string;
  disabled?: boolean;
}

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
      className="block w-full px-3 py-2 bg-cream text-ink border border-ink/30 font-sans text-sm placeholder:text-ink/60 focus:outline-none focus:border-ink disabled:opacity-50"
    />
  );
}
