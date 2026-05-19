"""scripts/smoke_r2_roundtrip.py — CTK-036 cut-2 verification smoke test.

One-shot round-trip against the live R2 bucket: build a tiny WebP via
Pillow, PUT it under a `_smoke/` prefix, fetch it back via the public
custom-domain URL, assert HTTP 200 + body bytes match. Validates that
the boto3 S3-compat client + Cloudflare R2 endpoint + custom domain
binding all line up before any production code paths exercise the
swap.

Invocation (Jon-side terminal — needs R2_* env vars in .env):

    python -m scripts.smoke_r2_roundtrip

Exit codes: 0 = round-trip passed, 1 = any failure (PUT, HEAD, GET,
body mismatch). Re-runnable; PUT uses `--upsert`-equivalent semantics
(R2 last-write-wins on the same key) and the smoke object is left in
place for inspection — delete via R2 dashboard or a follow-up CLI call
when no longer useful.

Permanent script (not a temp shim): re-run after credential rotation,
custom-domain re-binding, or any cut-2-adjacent change to verify the
round-trip still holds.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from io import BytesIO
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from PIL import Image

from scrapers.common import images
# scrapers.common.db imports python-dotenv side-effect; re-import here so
# .env is loaded even when invoked outside a scrape (where db.py would
# normally be the first touch).
from scrapers.common import db  # noqa: F401 — side-effect import for .env load


def _make_test_webp() -> bytes:
    """50x50 solid-coral-orange WebP, ~200 bytes. Small enough to round-trip
    fast; identifiable enough to spot in the R2 dashboard."""
    img = Image.new("RGB", (50, 50), (243, 132, 92))
    out = BytesIO()
    img.save(out, "WEBP", quality=75, method=6)
    return out.getvalue()


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    object_key = f"_smoke/cut2-{timestamp}.webp"
    body = _make_test_webp()
    public_url = images._public_url(object_key)

    print(f"smoke object_key:  {object_key}")
    print(f"smoke public_url:  {public_url}")
    print(f"body bytes:        {len(body)}")

    # Step 1 — PUT via boto3 S3-compat
    try:
        s3 = images._get_s3_client()
        s3.put_object(
            Bucket=os.environ["R2_BUCKET_NAME"],
            Key=object_key,
            Body=body,
            ContentType="image/webp",
        )
    except KeyError as e:
        print(f"FAIL: missing env var {e}; populate .env with R2_ACCOUNT_ID, "
              f"R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME.")
        return 1
    except Exception as e:  # noqa: BLE001 — botocore exceptions heterogeneous
        print(f"FAIL at PUT: {type(e).__name__}: {e}")
        return 1
    print("PUT ok")

    # Step 2 — GET via public custom domain
    try:
        req = Request(public_url, headers={"User-Agent": "coralticker-smoke/1.0"})
        with urlopen(req, timeout=10) as resp:
            status = resp.status
            fetched = resp.read()
    except HTTPError as e:
        print(f"FAIL at GET: HTTP {e.code} — {e.reason}")
        return 1
    except URLError as e:
        print(f"FAIL at GET: URL error — {e.reason}")
        return 1

    print(f"GET status:        {status}")
    print(f"GET body bytes:    {len(fetched)}")

    if status != 200:
        print(f"FAIL: expected HTTP 200, got {status}")
        return 1
    if fetched != body:
        print(f"FAIL: body bytes mismatch (PUT {len(body)} vs GET {len(fetched)})")
        return 1

    print()
    print("PASS: round-trip clean.")
    print(f"Smoke object left at {public_url} for inspection.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
