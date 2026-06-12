// Required-env read with throw-on-missing. Call at MODULE scope so a missing
// var fails the build/boot loudly instead of shipping a dead surface (the
// href={undefined} renders a non-link defect class).
//
// SERVER-ONLY. The dynamic process.env[name] lookup is invisible to Next's
// static NEXT_PUBLIC_* inlining, so in a client bundle this reads the empty
// env stub and throws AT THE VISITOR — the exact dead-surface class the helper
// exists to kill, relocated to runtime. Never call it from a 'use client' tree
// and never pass a NEXT_PUBLIC_ name; if a consumer ever drifts client-ward,
// add the `server-only` marker package here so the build fails instead.
//
// Empty string counts as missing, matching the falsy check every pre-extraction
// site used.

export function getRequiredEnv(name: string): string {
  const raw = process.env[name];
  if (!raw) {
    throw new Error(`${name} must be set. See .env.example.`);
  }
  return raw;
}
