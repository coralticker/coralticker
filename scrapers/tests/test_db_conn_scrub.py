"""scrapers/tests/test_db_conn_scrub.py — CTK-118 Fix #1 unit coverage for
`scrapers.common.db._scrub_conninfo`.

Runnable as:
  python -m scrapers.tests.test_db_conn_scrub
or
  python scrapers/tests/test_db_conn_scrub.py

No pytest dependency. No DB connection — _scrub_conninfo is a pure string
transform over a synthetic error message + a conninfo string. The connect
path itself is not exercised (no live Neon); the scrub is the load-bearing
leak-closer and the scrub is what we pin.

The 06-04 incident: psycopg echoed a *transformed* form of the conninfo
(URL reformatted into host=/user=/password= components) that GH Actions
literal-value masking missed. The transformed-component case below is the
exact regression hook.

Coverage:
  test_literal_url_redacted          literal URL in message
  test_transformed_component_form    host=/user=/password= echo (the 06-04 shape)
  test_password_alone_redacted       just the password token in the message
  test_unparseable_conninfo_falls_back  malformed conninfo -> static redacted line
  test_unparseable_never_raises      scrub never raises out of the except path
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import psycopg

from scrapers.common.db import _CONNINFO_PLACEHOLDER, _scrub_conninfo, get_conn

# Synthetic conninfo — looks like a real Neon URL but is fabricated for the
# test. Components are distinctive so a survival check is unambiguous.
CONNINFO = (
    "postgresql://neondb_owner:npg_TESTSECRET999@"
    "ep-test-host-abc.us-east-2.aws.neon.tech/neondb?sslmode=require"
)
PASSWORD = "npg_TESTSECRET999"
HOST = "ep-test-host-abc.us-east-2.aws.neon.tech"
USER = "neondb_owner"

# Anything in this set surviving the scrub is a leak.
SENSITIVE_TOKENS = [CONNINFO, PASSWORD, HOST, USER]


def _assert_clean(out: str):
    """No sensitive token survives + the placeholder (or static fallback) is
    present so we know redaction actually fired, not a no-op."""
    for tok in SENSITIVE_TOKENS:
        assert tok not in out, f"sensitive token {tok!r} survived scrub: {out!r}"
    assert _CONNINFO_PLACEHOLDER in out or "value redacted" in out, (
        f"scrub produced no redaction marker; got: {out!r}"
    )


def test_literal_url_redacted():
    """psycopg echoed the conninfo URL verbatim in the error string."""
    msg = f'connection failed: could not connect using "{CONNINFO}"'
    _assert_clean(_scrub_conninfo(msg, CONNINFO))


def test_transformed_component_form():
    """The 06-04 shape: URL reformatted into host=/user=/password= components.
    Literal-substring masking misses this; component redaction must catch it."""
    msg = (
        f"connection to server at \"{HOST}\" failed: "
        f"FATAL: password authentication failed for user \"{USER}\" "
        f"(conninfo: host={HOST} user={USER} password={PASSWORD} dbname=neondb)"
    )
    _assert_clean(_scrub_conninfo(msg, CONNINFO))


def test_password_alone_redacted():
    """Only the password token appears in the message — still must not survive."""
    msg = f"authentication failed (secret: {PASSWORD})"
    _assert_clean(_scrub_conninfo(msg, CONNINFO))


def test_unparseable_conninfo_falls_back():
    """Malformed conninfo (the F2 case) makes conninfo_to_dict raise; the
    scrub must fall back to a static redacted line, never leak, never crash."""
    bad_conninfo = "not-a-postgres-url-but-still-secret-ish"
    msg = f"could not parse: {bad_conninfo}"
    out = _scrub_conninfo(msg, bad_conninfo)
    assert bad_conninfo not in out, f"unparseable conninfo survived: {out!r}"
    assert out == "conninfo unparseable; value redacted", (
        f"expected static fallback line; got: {out!r}"
    )


def test_unparseable_never_raises():
    """Belt-and-suspenders: even with junk inputs the scrub returns a string
    rather than raising — a scrub that throws replaces a leak with a crash."""
    out = _scrub_conninfo("some error", "postgresql://[malformed")
    assert isinstance(out, str), f"scrub must return a string; got: {out!r}"


def test_options_endpoint_id_redacted():
    """CTK-118 /code-review F1: the non-SNI/pooler URL carries the Neon
    endpoint id as options=endpoint=ep-x. psycopg can echo the *bare* endpoint
    id, which whole-host (or whole-options-value) redaction misses. The scrub
    must redact the bare endpoint id, not just the `endpoint=ep-x` token."""
    endpoint = "ep-test-endpoint-xyz-12345"
    conninfo = (
        f"postgresql://{USER}:{PASSWORD}@pooler.us-east-2.aws.neon.tech/neondb"
        f"?options=endpoint%3D{endpoint}&sslmode=require"
    )
    # psycopg echoes the bare endpoint id, not the whole "endpoint=ep-x" token.
    msg = f'connection failed for endpoint "{endpoint}": timeout expired'
    out = _scrub_conninfo(msg, conninfo)
    assert endpoint not in out, f"bare endpoint id survived scrub: {out!r}"
    assert _CONNINFO_PLACEHOLDER in out, f"no redaction marker; got: {out!r}"


def test_reraise_preserves_type_and_scrubs():
    """CTK-118 /code-review F3: pin the get_conn() re-raise path. For each of
    the two caught types, a connect that raises with a sensitive message must
    re-raise (a) the SAME type, (b) a scrubbed message, (c) with `from None`
    (no __cause__, context suppressed) so the un-scrubbed original cannot reach
    a printed traceback. Locks the docstring's "callers' except OperationalError
    routing is unchanged" hook + the two-type except tuple."""
    raised_msg = (
        f'FATAL: password authentication failed for user "{USER}" '
        f"(host={HOST} user={USER} password={PASSWORD} dbname=neondb)"
    )
    for exc_type in (psycopg.OperationalError, psycopg.ProgrammingError):
        with mock.patch.dict(os.environ, {"NEON_DATABASE_URL": CONNINFO}):
            with mock.patch("psycopg.connect", side_effect=exc_type(raised_msg)):
                raised = None
                try:
                    get_conn()
                except Exception as e:  # noqa: BLE001 — capture for assertions
                    raised = e
        assert raised is not None, f"get_conn must re-raise on {exc_type.__name__}"
        assert type(raised) is exc_type, (
            f"re-raise must preserve type; expected {exc_type.__name__}, "
            f"got {type(raised).__name__}"
        )
        for tok in SENSITIVE_TOKENS:
            assert tok not in str(raised), (
                f"sensitive token {tok!r} survived re-raise: {raised}"
            )
        assert raised.__cause__ is None, "`from None` must clear __cause__"
        assert raised.__suppress_context__ is True, (
            "`from None` must suppress the chained context"
        )


# --- Test runner ----------------------------------------------------------
TESTS = [
    test_literal_url_redacted,
    test_transformed_component_form,
    test_password_alone_redacted,
    test_unparseable_conninfo_falls_back,
    test_unparseable_never_raises,
    test_options_endpoint_id_redacted,
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
