"""scrapers/tests/test_raw_prod_connect_guard.py — CTK-222: unit coverage for the
raw-`psycopg.connect` prod-path guard (runtime factory + static AST arm).

Runnable as:
  python -m scrapers.tests.test_raw_prod_connect_guard
or
  python scrapers/tests/test_raw_prod_connect_guard.py

No DB connection. The runtime arm drives conftest._build_prod_connect_guard with a
SENTINEL real_connect, so the guarded prod case raises before any connection attempt
and the pass-through cases return the sentinel — never a live socket. NOT marked
requires_db; MUST pass in CI (this is the load-bearing raw-bypass closer for CTK-215's
prod-write class — the escape hatch D2 missed, per CTK-219's onboarding follow-on).

Coverage:
  runtime — raw connect to the prod DSN raises the CTK-222 RuntimeError (would pass the
            sentinel through if the raise were removed); pooler-form of prod also raises;
            branch DSN + kwarg-less connect + unset-prod all pass through to real_connect;
            the branch pass-through decision is pinned directly via _dsn_targets_same_db.
  static  — the AST arm flags psycopg.connect(...) / an import-gated bare connect(...),
            and does NOT flag a bare connect(...) without the import nor a
            mock.patch("psycopg.connect") string arg.
"""

from __future__ import annotations

import ast
import os
import sys
from unittest import mock

from scrapers.common import db
from scrapers.tests.conftest import _build_prod_connect_guard
from scripts.ctk219_verify_no_prod_conn import _forbidden_conn_call_lines

# Synthetic DSNs — fabricated, distinctive components so collision checks are
# unambiguous. Prod has a direct + a pooler host form of the SAME DB; the branch has a
# DIFFERENT endpoint id (no collision). Mirrors test_get_test_conn_guard's fixtures.
PROD_HOST_DIRECT = "ep-prod-abc-111111.us-east-2.aws.neon.tech"
PROD_HOST_POOLER = "ep-prod-abc-111111-pooler.us-east-2.aws.neon.tech"
PROD_DIRECT_DSN = f"postgresql://neondb_owner:npg_PRODSECRET999@{PROD_HOST_DIRECT}/neondb?sslmode=require"
PROD_POOLER_DSN = f"postgresql://neondb_owner:npg_PRODSECRET999@{PROD_HOST_POOLER}/neondb?sslmode=require"

BRANCH_HOST = "ep-branch-xyz-222222.us-east-2.aws.neon.tech"
BRANCH_DSN = f"postgresql://neondb_owner:npg_BRANCHSECRET999@{BRANCH_HOST}/neondb?sslmode=require"

_SENTINEL = object()


def _sentinel_connect(*args, **kwargs):
    """Stand-in for the real psycopg.connect. Returning a sentinel (never a socket)
    means a pass-through is observable and the raise path is the only way this test
    sees an exception — so removing the guard's raise flips the prod case to a
    sentinel return and fails the assertion."""
    return _SENTINEL


# --- Runtime guard --------------------------------------------------------------


def test_raw_prod_connect_raises():
    """A raw connect whose positional DSN equals prod raises the CTK-222 RuntimeError,
    and real_connect is never reached. Exercises the exact-string-equality leg of
    _dsn_targets_same_db (dsn == NEON_DATABASE_URL)."""
    guard = _build_prod_connect_guard(_sentinel_connect)
    with mock.patch.dict(os.environ, {"NEON_DATABASE_URL": PROD_DIRECT_DSN}, clear=True):
        try:
            guard(PROD_DIRECT_DSN)
        except RuntimeError as e:
            assert "CTK-222" in str(e), f"expected CTK-222 in the guard message; got: {e}"
        else:
            raise AssertionError("raw connect to the prod DSN must raise; got a pass-through")


def test_pooler_form_of_prod_raises():
    """A pooler-host form of the prod DSN is a different STRING but the same database
    -> raises. Pins that the guard uses _dsn_targets_same_db (normalization leg), not a
    bare ==, so the Neon pooler-vs-direct bypass is closed."""
    guard = _build_prod_connect_guard(_sentinel_connect)
    with mock.patch.dict(os.environ, {"NEON_DATABASE_URL": PROD_DIRECT_DSN}, clear=True):
        try:
            guard(PROD_POOLER_DSN)
        except RuntimeError as e:
            assert "CTK-222" in str(e), f"expected CTK-222 in the guard message; got: {e}"
        else:
            raise AssertionError("pooler-form connect to prod must raise; got a pass-through")


def test_prod_dsn_via_conninfo_kwarg_raises():
    """The DSN passed as the `conninfo=` kwarg (psycopg 3) resolves the same as a
    positional and raises — the bypass isn't dodged by naming the arg."""
    guard = _build_prod_connect_guard(_sentinel_connect)
    with mock.patch.dict(os.environ, {"NEON_DATABASE_URL": PROD_DIRECT_DSN}, clear=True):
        try:
            guard(conninfo=PROD_DIRECT_DSN, autocommit=True)
        except RuntimeError as e:
            assert "CTK-222" in str(e), f"expected CTK-222 in the guard message; got: {e}"
        else:
            raise AssertionError("prod DSN via conninfo= kwarg must raise; got a pass-through")


def test_branch_dsn_passes_through():
    """A distinct branch DSN (different endpoint id) passes the predicate and reaches
    real_connect — the guard must not false-block a legitimate test connection (this is
    the get_test_conn path under the patched psycopg.connect)."""
    guard = _build_prod_connect_guard(_sentinel_connect)
    with mock.patch.dict(os.environ, {"NEON_DATABASE_URL": PROD_DIRECT_DSN}, clear=True):
        assert guard(BRANCH_DSN, autocommit=True) is _SENTINEL, (
            "a distinct branch DSN must pass through to real_connect"
        )


def test_branch_predicate_is_false_directly():
    """Pin the pass-through DECISION at its source: _dsn_targets_same_db(branch, prod)
    is False. No connect — the predicate is what the guard trusts, asserted directly."""
    assert db._dsn_targets_same_db(BRANCH_DSN, PROD_DIRECT_DSN) is False, (
        "a distinct branch DSN must not be judged the same database as prod"
    )


def test_unset_prod_url_fails_open():
    """NEON_DATABASE_URL unset -> nothing to collide against -> pass through, even for a
    prod-looking DSN. Mirrors get_test_conn's `prod_url is not None` fail-open."""
    guard = _build_prod_connect_guard(_sentinel_connect)
    with mock.patch.dict(os.environ, {}, clear=True):
        assert guard(PROD_DIRECT_DSN) is _SENTINEL, (
            "with NEON_DATABASE_URL unset the guard must pass through"
        )


def test_keyword_only_connect_passes_through():
    """A connect with no DSN string (all keyword host=/dbname= params) resolves to no
    DSN and passes through — the closed bypass class is always a positional/kwarg DSN
    string, not decomposed connection params."""
    guard = _build_prod_connect_guard(_sentinel_connect)
    with mock.patch.dict(os.environ, {"NEON_DATABASE_URL": PROD_DIRECT_DSN}, clear=True):
        assert guard(host="localhost", dbname="whatever") is _SENTINEL, (
            "a keyword-params connect (no DSN string) must pass through"
        )


# --- Static AST arm -------------------------------------------------------------


def test_static_flags_psycopg_connect_attribute():
    """The AST arm flags `psycopg.connect(...)` and `psycopg2.connect(...)`."""
    src = "import psycopg\npsycopg.connect(PROD)\npsycopg2.connect(PROD)\n"
    hits = _forbidden_conn_call_lines(ast.parse(src))
    assert hits == [2, 3], f"expected both attribute-connect calls flagged; got {hits}"


def test_static_flags_import_gated_bare_connect():
    """`from psycopg import connect; connect(...)` is flagged — the bare Name arm fires
    because the module imported connect by that name."""
    src = "from psycopg import connect\nconnect(PROD)\n"
    hits = _forbidden_conn_call_lines(ast.parse(src))
    assert hits == [2], f"expected the import-gated bare connect flagged; got {hits}"


def test_static_ignores_bare_connect_without_import():
    """A bare `connect(...)` with NO `from psycopg import connect` is NOT flagged — the
    gate is what keeps mock sockets / unrelated `connect(` APIs from false-flagging."""
    src = "sock.connect(addr)\nconnect(whatever)\n"
    hits = _forbidden_conn_call_lines(ast.parse(src))
    assert hits == [], f"bare connect without the psycopg import must not flag; got {hits}"


def test_static_ignores_mock_patch_string():
    """`mock.patch(\"psycopg.connect\")` is a string arg, not a Call to psycopg.connect
    — the AST walk must not flag it (the whole reason this is AST, not a line grep)."""
    src = 'from unittest import mock\nwith mock.patch("psycopg.connect"):\n    pass\n'
    hits = _forbidden_conn_call_lines(ast.parse(src))
    assert hits == [], f"a mock.patch(\"psycopg.connect\") string must not flag; got {hits}"


def test_static_still_flags_get_conn():
    """The pre-existing CTK-219 get_conn arm is intact — both attribute and bare Name."""
    src = "import db\ndb.get_conn()\nget_conn()\n"
    hits = _forbidden_conn_call_lines(ast.parse(src))
    assert hits == [2, 3], f"expected both get_conn calls still flagged; got {hits}"


# --- Test runner ----------------------------------------------------------------
TESTS = [
    test_raw_prod_connect_raises,
    test_pooler_form_of_prod_raises,
    test_prod_dsn_via_conninfo_kwarg_raises,
    test_branch_dsn_passes_through,
    test_branch_predicate_is_false_directly,
    test_unset_prod_url_fails_open,
    test_keyword_only_connect_passes_through,
    test_static_flags_psycopg_connect_attribute,
    test_static_flags_import_gated_bare_connect,
    test_static_ignores_bare_connect_without_import,
    test_static_ignores_mock_patch_string,
    test_static_still_flags_get_conn,
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
