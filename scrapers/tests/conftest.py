"""scrapers/tests/conftest.py — CTK-208: shared pytest fixtures for the live-Neon DB
suites + a requires_db skip gate.

Before this file, 33 test functions across 10 modules declared conn / vendor /
coral_alpha / coral_beta parameters that pytest resolves as fixtures. No conftest
defined them, so a bare `pytest scrapers/tests/` raised 33 fixture-not-found ERRORS
(distinct from failures — collection never reached the assertions). Each module's
main() block already built its own conn + isolated _ctk*_test vendor for script-mode
(`python -m scrapers.tests.test_x`); this hoists that pattern into shared fixtures so
pytest-mode resolves the same shapes. Script-mode is unaffected — those modules still
build their own conn + vendor in main() and never import this file.

Two behaviors:
  1. requires_db tests SKIP (not error, not fail) when NEON_DATABASE_URL is absent.
     CI already deselects via `-m "not requires_db"`; this makes a bare local
     `pytest scrapers/tests/` on a no-.env checkout skip cleanly instead of erroring
     on connect — so `pytest scrapers/tests/` is 0-errors in BOTH environments
     (CTK-208 closure gate c).
  2. conn / vendor / coral_alpha / coral_beta fixtures provide a live psycopg
     connection + the module's own isolated test vendor + (for rematch) its two
     synthetic named_corals.

ISOLATION (CTK-208 — why these are function-scoped + delegated): the per-file DB
suites were written for a FRESH connection per file (each main() opens its own
`with db.get_conn()`) and a SEPARATE isolated vendor per file (_ctk032_test,
_ctk124_test, ...). A single shared session-scoped conn + one shared vendor broke
both: a long-lived Neon connection is dropped server-side mid-run (OperationalError),
and one vendor shared across files cross-contaminates the per-vendor RPC reads. So:
  - `conn` is FUNCTION-scoped — a fresh connection per test, exactly mirroring the
    per-file isolation, never idle long enough for Neon to drop it.
  - `vendor` / `coral_*` DELEGATE to the test module's own _setup_test_vendor /
    _setup_test_coral. pytest-mode then gets byte-for-byte what script-mode's main()
    builds (which already passes for every suite) — original slug, active flag, and
    return shape. No vendor is shared across files; rematch's active=true vendor (it
    scans `WHERE v.active = TRUE`) comes from its own _setup_test_vendor for free.
"""

from __future__ import annotations

import os

import pytest

from scrapers.common import db


def _have_db() -> bool:
    return bool(os.environ.get("NEON_DATABASE_URL"))


def pytest_collection_modifyitems(config, items):
    """Turn the would-be live-DB connect ERROR into a clean SKIP when there is no
    NEON_DATABASE_URL. Every live-DB test is marked requires_db (via @mark_requires_db
    or module-level pytestmark); CI already deselects them with -m "not requires_db",
    and this covers a bare local run with no .env."""
    if _have_db():
        return
    skip_db = pytest.mark.skip(reason="NEON_DATABASE_URL not set — live-DB (requires_db) test")
    for item in items:
        if "requires_db" in item.keywords:
            item.add_marker(skip_db)


@pytest.fixture
def conn():
    """Fresh live psycopg connection per test (autocommit + dict_row per
    scrapers.common.db). Function-scoped so no single connection is held long enough
    for Neon to drop it mid-suite. Skips if NEON_DATABASE_URL is absent —
    belt-and-suspenders with the marker gate above."""
    if not _have_db():
        pytest.skip("NEON_DATABASE_URL not set — live-DB test")
    with db.get_conn() as c:
        yield c


@pytest.fixture
def vendor(conn, request) -> dict:
    """The test module's own isolated vendor — delegates to that module's
    _setup_test_vendor(conn) so pytest-mode gets exactly what script-mode builds
    (original slug + active flag + return shape). No vendor is shared across files."""
    setup = getattr(request.module, "_setup_test_vendor", None)
    if setup is None:
        pytest.skip(
            f"{request.module.__name__} requests the `vendor` fixture but defines no "
            f"module-level _setup_test_vendor(conn)"
        )
    return setup(conn)


def _setup_coral(conn, request, prefix: str) -> dict:
    """Delegate to the test module's _setup_test_coral + TEST_CORAL_<prefix>_*
    constants so the cascade matches the listings the rematch bodies insert. Same
    getattr-or-skip guard as `vendor` — a module requesting a coral fixture without
    the setup helper / constants skips rather than AttributeErrors."""
    m = request.module
    setup = getattr(m, "_setup_test_coral", None)
    if setup is None:
        pytest.skip(
            f"{m.__name__} requests a coral fixture but defines no module-level "
            f"_setup_test_coral(conn, canonical, normalized, slug)"
        )
    try:
        canonical = getattr(m, f"TEST_CORAL_{prefix}_CANONICAL")
        normalized = getattr(m, f"TEST_CORAL_{prefix}_NORMALIZED")
        slug = getattr(m, f"TEST_CORAL_{prefix}_SLUG")
    except AttributeError:
        pytest.skip(f"{m.__name__} is missing TEST_CORAL_{prefix}_* constants for the coral fixture")
    return setup(conn, canonical, normalized, slug)


@pytest.fixture
def coral_alpha(conn, request) -> dict:
    """rematch's synthetic coral A (see _setup_coral)."""
    return _setup_coral(conn, request, "ALPHA")


@pytest.fixture
def coral_beta(conn, request) -> dict:
    """rematch's synthetic coral B (see _setup_coral)."""
    return _setup_coral(conn, request, "BETA")
