import type { Config } from 'tailwindcss';

export default {
  content: [
    './app/**/*.{ts,tsx,mdx}',
    './components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        cream: 'var(--color-cream)',
        ink: 'var(--color-ink)',
        forest: '#1B5E20',
        // CTK-129 served-neutral re-spec (branding-guide §"Served-neutral
        // re-spec", 2026-06-05). ink/NN opacity modifiers never compiled —
        // ink lacks <alpha-value>, deliberately unchanged (the config flip
        // was REJECTED at canon: it would repaint the adopted surfaces).
        // These literals adopt what actually served:
        line: '#E5E7EB', // hairlines/borders/dividers/under-rules (was preflight border default)
        mute: '#9CA3AF', // placeholder text ONLY (was preflight ::placeholder); AA exception named at canon, Phase 3 revisit
        wash: '#EAE6E0', // skeleton bars / image-slot / row-hover repaint (bg-ink/NN served transparent); STARTING value — final hex at Jon eyeball
      },
      fontFamily: {
        sans: ['var(--font-plex-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['var(--font-plex-mono)', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config;
