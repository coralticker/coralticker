"""scrapers/tests/test_get_test_conn_guard.py — CTK-215 /code-review fold #2:
unit coverage for `scrapers.common.db.get_test_conn`'s fail-closed guard.

Runnable as:
  python -m scrapers.tests.test_get_test_conn_guard
or
  python scrapers/tests/test_get_test_conn_guard.py

No DB connection — every case patches `psycopg.connect`, so this is a pure unit
test of the guard logic and the scrub-on-connect-error re-raise. It is NOT marked
requires_db and MUST pass in CI (the guard is the load-bearing prod-write
closer; we pin its three failure modes plus the no-false-collision path).

Coverage:
  test_unset_raises_not_configured        TEST_DATABASE_URL absent -> raise, no connect
  test_exact_prod_collision_raises        TEST == NEON exact-string -> raise, no connect
  test_pooler_vs_direct_collision_raises  pooler-host form of prod -> raise, no connect
  test_distinct_branch_does_not_collide   real branch DSN -> no false collision, connects
  test_reraise_preserves_type_and_scrubs  connect-error re-raised with scrubbed message
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import psycopg

from scrapers.common.db import (
    TestDatabaseNotConfigured,
    TestDatabasePointsAtProd,
    get_test_conn,
)

# Synthetic DSNs — fabricated, distinctive components so survival/collision
# checks are unambiguous. Prod has a direct + a pooler host form of the SAME DB
# (the fold-#3 case). The branch has a DIFFERENT endpoint id (no collision).
PROD_HOST_DIRECT = "ep-prod-abc-111111.us-east-2.aws.neon.tech"
PROD_HOST_POOLER = "ep-prod-abc-111111-pooler.us-east-2.aws.neon.tech"
PROD_DIRECT_DSN = f"postgresql://neondb_owner:npg_PRODSECRET999@{PROD_HOST_DIRECT}/neondb?sslmode=require"
PROD_POOLER_DSN = f"postgresql://neondb_owner:npg_PRODSECRET999@{PROD_HOST_POOLER}/neondb?sslmode=require"

BRANCH_HOST = "ep-branch-xyz-222222.us-east-2.aws.neon.tech"
BRANCH_DSN = f"postgresql://neondb_owner:npg_BRANCHSECRET999@{BRANCH_HOST}/neondb?sslmode=require"

# A well-formed test DSN distinct from prod (no collision) carrying sensitive
# tokens, for the scrub-on-connect-error re-raise case.
TEST_USER = "neondb_owner"
TEST_PASSWORD = "npg_TESTGUARDSECRET999"
TEST_HOST = "ep-test-guard-333333.us-east-2.aws.neon.tech"
TEST_DSN = f"postgresql://{TEST_USER}:{TEST_PASSWORD}@{TEST_HOST}/neondb?sslmode=require"


def test_unset_raises_not_configured():
    """TEST_DATABASE_URL absent -> TestDatabaseNotConfigured, and psycopg.connect
    is never reached (fail closed before any connection attempt). clear=True wipes
    the env so a developer .env-loaded TEST_DATABASE_URL can't leak into the case."""
    with mock.patch.dict(os.environ, {"NEON_DATABASE_URL": PROD_DIRECT_DSN}, clear=True):
        with mock.patch("psycopg.connect") as m_connect:
            try:
                get_test_conn()
            except TestDatabaseNotConfigured:
                pass
            else:
                raise AssertionError("expected TestDatabaseNotConfigured when TEST_DATABASE_URL is unset")
            assert not m_connect.called, "connect must not be attempted when TEST_DATABASE_URL is unset"


def test_exact_prod_collision_raises():
    """TEST == NEON byte-for-byte -> TestDatabasePointsAtProd, connect uncalled."""
    with mock.patch.dict(
        os.environ,
        {"NEON_DATABASE_URL": PROD_DIRECT_DSN, "TEST_DATABASE_URL": PROD_DIRECT_DSN},
        clear=True,
    ):
        with mock.patch("psycopg.connect") as m_connect:
            try:
                get_test_conn()
            except TestDatabasePointsAtProd:
                pass
            else:
                raise AssertionError("expected TestDatabasePointsAtProd on exact-string prod match")
            assert not m_connect.called, "connect must not be attempted on prod collision"


def test_pooler_vs_direct_collision_raises():
    """fold #3: a pooler-host form of the prod DSN is a different STRING but the
    same database -> TestDatabasePointsAtProd, connect uncalled. String-equality
    alone would wave this through as a 'test' target."""
    with mock.patch.dict(
        os.environ,
        {"NEON_DATABASE_URL": PROD_DIRECT_DSN, "TEST_DATABASE_URL": PROD_POOLER_DSN},
        clear=True,
    ):
        with mock.patch("psycopg.connect") as m_connect:
            try:
                get_test_conn()
            except TestDatabasePointsAtProd:
                pass
            else:
                raise AssertionError("expected TestDatabasePointsAtProd on pooler-vs-direct prod form")
            assert not m_connect.called, "connect must not be attempted on pooler-vs-direct collision"


def test_distinct_branch_does_not_collide():
    """A real Neon branch (different endpoint id) must NOT false-collide — the
    normalize step can't be so aggressive it blocks legitimate branches. Guard
    passes -> connect is reached (patched to a sentinel)."""
    sentinel = object()
    with mock.patch.dict(
        os.environ,
        {"NEON_DATABASE_URL": PROD_DIRECT_DSN, "TEST_DATABASE_URL": BRANCH_DSN},
        clear=True,
    ):
        with mock.patch("psycopg.connect", return_value=sentinel) as m_connect:
            out = get_test_conn()
            assert out is sentinel, "a distinct branch DSN must pass the guard and connect"
            assert m_connect.called, "connect must be attempted for a non-colliding branch DSN"


def test_reraise_preserves_type_and_scrubs():
    """Mirror test_db_conn_scrub.test_reraise_preserves_type_and_scrubs for the
    TEST path: a connect that raises with a sensitive message must re-raise (a) the
    SAME type, (b) a scrubbed message (no TEST DSN component survives), (c) with
    `from None` (context suppressed). TEST_DSN is distinct from prod so the guard
    passes and the connect path is what's exercised."""
    raised_msg = (
        f'FATAL: password authentication failed for user "{TEST_USER}" '
        f"(host={TEST_HOST} user={TEST_USER} password={TEST_PASSWORD} dbname=neondb)"
    )
    for exc_type in (psycopg.OperationalError, psycopg.ProgrammingError):
        with mock.patch.dict(
            os.environ,
            {"NEON_DATABASE_URL": PROD_DIRECT_DSN, "TEST_DATABASE_URL": TEST_DSN},
            clear=True,
        ):
            with mock.patch("psycopg.connect", side_effect=exc_type(raised_msg)):
                raised = None
                try:
                    get_test_conn()
                except Exception as e:  # noqa: BLE001 — capture for assertions
                    raised = e
        assert raised is not None, f"get_test_conn must re-raise on {exc_type.__name__}"
        assert type(raised) is exc_type, (
            f"re-raise must preserve type; expected {exc_type.__name__}, got {type(raised).__name__}"
        )
        for tok in (TEST_DSN, TEST_PASSWORD, TEST_HOST):
            assert tok not in str(raised), f"sensitive token {tok!r} survived re-raise: {raised}"
        assert raised.__cause__ is None, "`from None` must clear __cause__"
        assert raised.__suppress_context__ is True, "`from None` must suppress the chained context"


TESTS = [
    test_unset_raises_not_configured,
    test_exact_prod_collision_raises,
    test_pooler_vs_direct_collision_raises,
    test_distinct_branch_does_not_collide,
    test_reraise_preserves_type_and_scrubs,
]


def main() -> int:
    passed = 0
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001 — surface unexpected exception type
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed (total {len(TESTS)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
