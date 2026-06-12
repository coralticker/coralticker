// Server-only by CONVENTION — nothing mechanical excludes this module from a
// client bundle; if its import graph ever nears one, add the `server-only`
// marker package (build-time error) rather than trusting where the env read
// happens.

import { neon, type NeonQueryFunction } from '@neondatabase/serverless';
// Relative + extensioned, NOT '@/lib/env': this file is dynamically imported
// by bare-node entrypoints, and node --experimental-strip-types resolves no
// tsconfig path aliases — an '@/' specifier here crashes the digest cron with
// ERR_MODULE_NOT_FOUND.
import { getRequiredEnv } from '../env.ts';

const NEON_DATABASE_URL = getRequiredEnv('NEON_DATABASE_URL');

let _sql: NeonQueryFunction<false, false> | null = null;

export function getNeonSql(): NeonQueryFunction<false, false> {
  if (_sql === null) {
    _sql = neon(NEON_DATABASE_URL);
  }
  return _sql;
}
