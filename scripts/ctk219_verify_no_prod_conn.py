"""CTK-219 D2 / CTK-222 — pre-push guard: no prod connection call under scrapers/tests/.

Static half of the prod-path guard. The runtime half (conftest autouse fixtures) swaps
db.get_conn and psycopg.connect for raising/guarding stubs during every test, but a
module-attribute monkeypatch cannot intercept a `from scrapers.common.db import get_conn`
direct-import call. This script closes that gap: it parses every test module's AST and
FAILS on any real prod-connection call, so a test can't (re)grow the prod-write path that
CTK-213/CTK-215 closed. Two call classes:

  - get_conn()          — `db.get_conn(...)` (Attribute) or a bare `get_conn(...)` (Name).
                          The CTK-219 D2 class (routes through the prod db.get_conn path).
  - psycopg.connect()   — `psycopg.connect(...)` / `psycopg2.connect(...)` (Attribute), or
                          a bare `connect(...)` (Name) ONLY in a module that actually did
                          `from psycopg[2] import connect`. The CTK-222 raw-bypass class
                          (connects to prod without touching db.get_conn).

The bare-`connect(` Name arm is gated on a real import because — unlike the distinctive
get_conn — a bare `connect(` collides with mock sockets, asyncio, and unrelated APIs; we
only flag it when the module imported psycopg's connect by that name.

AST, not a line grep: these names appear in docstrings/comments (conftest, the scrub
test's docstring) and inside `mock.patch("psycopg.connect")` string args that a text scan
would false-flag. Walking Call nodes counts only genuine calls and ignores prose + patch
strings. get_test_conn() is a different name and never matches.

ALLOW-LIST: test_db_conn_scrub deliberately drives the prod re-raise/scrub path with
psycopg.connect mocked — it never opens a real connection. Mirror any addition here in
conftest._PROD_CONN_ALLOWED_MODULES.

Known limitation (matches the get_conn arm): an aliased module import
(`import psycopg as pg; pg.connect(...)`) is not caught. No test aliases the module; the
runtime autouse guard is the backstop if one ever does.

Read-only; no DB. Wired into .githooks/pre-push. Run standalone:
  python scripts/ctk219_verify_no_prod_conn.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent / "scrapers" / "tests"

# Bare test-file names whose prod-connection calls are intentional (psycopg.connect
# mocked, no real connection). Keep in lockstep with conftest._PROD_CONN_ALLOWED_MODULES.
_ALLOWED_FILES = frozenset({"test_db_conn_scrub.py"})


def _imported_connect_names(tree: ast.AST) -> set[str]:
    """Local names bound to psycopg[2].connect via `from psycopg import connect` /
    `from psycopg2 import connect [as alias]`. Empty when the module never imports
    connect by name — which is what gates the bare-`connect(` Name arm below, so a
    stray `connect(` on a mock/socket in an unrelated module is not false-flagged."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("psycopg", "psycopg2"):
            for alias in node.names:
                if alias.name == "connect":
                    names.add(alias.asname or alias.name)
    return names


def _forbidden_conn_call_lines(tree: ast.AST) -> list[int]:
    """Line numbers of every prod-connection call under the two guarded classes:

      - get_conn(...)        — `x.get_conn(...)` (Attribute) or bare `get_conn(...)` (Name)
      - psycopg[2].connect() — `psycopg.connect(...)` / `psycopg2.connect(...)` (Attribute),
                               or bare `connect(...)` (Name) ONLY where the module did
                               `from psycopg[2] import connect`.

    get_test_conn is a distinct name and is not matched."""
    connect_names = _imported_connect_names(tree)
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "get_conn":
                hits.append(node.lineno)
            elif (
                func.attr == "connect"
                and isinstance(func.value, ast.Name)
                and func.value.id in ("psycopg", "psycopg2")
            ):
                hits.append(node.lineno)
        elif isinstance(func, ast.Name):
            if func.id == "get_conn" or func.id in connect_names:
                hits.append(node.lineno)
    return hits


def main() -> int:
    offenders: list[str] = []
    # rglob (recursive) — a test module in a subdir of scrapers/tests/ (an
    # integration/ suite, a helpers package) must not slip past the guard. The
    # direct-import call form it might use is also the one the conftest
    # module-attribute monkeypatch cannot intercept, so this static pass is the
    # only net under it. (CTK-219 /code-review F3.)
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.name in _ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno in _forbidden_conn_call_lines(tree):
            offenders.append(f"{path.relative_to(TESTS_DIR.parent.parent)}:{lineno}")

    if offenders:
        print("CTK-219 D2 / CTK-222 FAILED: prod-connection call(s) found under scrapers/tests/:")
        for o in offenders:
            print(f"  - {o}")
        print(
            "\nLive-DB tests must use get_test_conn() (TEST_DATABASE_URL branch), never the\n"
            "prod path — neither db.get_conn() nor a raw psycopg.connect() to the prod DSN.\n"
            "If a call is intentional (psycopg.connect mocked, no real connection),\n"
            "allow-list the file in _ALLOWED_FILES here AND in\n"
            "conftest._PROD_CONN_ALLOWED_MODULES."
        )
        return 1

    print("CTK-219 D2 / CTK-222: no prod get_conn() or raw psycopg.connect() call under scrapers/tests/ — clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
