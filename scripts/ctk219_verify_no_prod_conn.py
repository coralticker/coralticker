"""CTK-219 D2 — pre-push guard: no prod get_conn() call under scrapers/tests/.

Static half of the D2 prod-path guard. The runtime half (conftest._forbid_prod_get_conn)
swaps db.get_conn for a raising stub during every test, but a module-attribute
monkeypatch cannot intercept a `from scrapers.common.db import get_conn` direct-import
call. This script closes that gap: it parses every test module's AST and FAILS on any
real call to get_conn() — both `db.get_conn(...)` (Attribute) and a bare `get_conn(...)`
(Name) — so a test can't (re)grow the prod-write path that CTK-213/CTK-215 closed.

AST, not a line grep: get_conn() appears in docstrings/comments (conftest, the scrub
test's docstring) that a text scan would false-flag. Walking Call nodes counts only
genuine calls and ignores prose. get_test_conn() is a different name and never matches.

ALLOW-LIST: test_db_conn_scrub deliberately calls get_conn() with psycopg.connect mocked
to pin the re-raise/scrub path — it never opens a real connection. Mirror any addition
here in conftest._PROD_CONN_ALLOWED_MODULES.

Read-only; no DB. Wired into .githooks/pre-push. Run standalone:
  python scripts/ctk219_verify_no_prod_conn.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent / "scrapers" / "tests"

# Bare test-file names whose get_conn() calls are intentional (psycopg.connect mocked,
# no real connection). Keep in lockstep with conftest._PROD_CONN_ALLOWED_MODULES.
_ALLOWED_FILES = frozenset({"test_db_conn_scrub.py"})


def _get_conn_call_lines(tree: ast.AST) -> list[int]:
    """Line numbers of every get_conn(...) call — `x.get_conn(...)` (Attribute) or a
    bare `get_conn(...)` (Name). get_test_conn is a distinct name and is not matched."""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get_conn":
            hits.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id == "get_conn":
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
        for lineno in _get_conn_call_lines(tree):
            offenders.append(f"{path.relative_to(TESTS_DIR.parent.parent)}:{lineno}")

    if offenders:
        print("CTK-219 D2 FAILED: prod get_conn() call(s) found under scrapers/tests/:")
        for o in offenders:
            print(f"  - {o}")
        print(
            "\nLive-DB tests must use get_test_conn() (TEST_DATABASE_URL branch), not the\n"
            "prod path. If a call is intentional (psycopg.connect mocked, no real\n"
            "connection), allow-list the file in _ALLOWED_FILES here AND in\n"
            "conftest._PROD_CONN_ALLOWED_MODULES."
        )
        return 1

    print("CTK-219 D2: no prod get_conn() call under scrapers/tests/ — clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
