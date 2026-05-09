"""Image-pipeline integration per CTK-019 calls #51-#56 + CTK-035 compression
cutover. Mirrors a vendor's image to the listing-images Supabase Storage
bucket; returns the public URL on success or None on failure. Synchronous,
1-attempt, image-only failure does NOT fail the row scrape (CTK-019 #55).

Forward-write per CTK-035 D-2 + D-3: compress to WebP @ 600px max long edge,
q75, before upload; bucket path is `{vendor_slug}/{handle}.webp`. Pillow
exception during compression falls through to raw-bytes upload at the
vendor-source extension/content-type — fail-soft semantics per arch
decision #55.

Parameters re-tuned in CTK-035 Session 3 from q80/800px → q75/600px after
PE Step 2 dry-run smoke surfaced an acceptance-ceiling miss: empirical
retention at q80/800px projected ~1.74 GB end-state vs. plan.md ≤1,000 MB.
q75/600px primary projects ~810 MB; q70/600px fallback (~630 MB) documented
in plan.md D-5 if visual-quality spot-check finds ≥3 of 8 visibly soft
against source-baseline.
"""

from __future__ import annotations

import logging
import os
import re
from io import BytesIO
from urllib.parse import urlparse

from PIL import Image

from scrapers.common import http

log = logging.getLogger(__name__)


_BUCKET = "listing-images"

# CTK-035 compression knobs (re-tuned Session 3). 600px max long edge stays
# above site.md /coral/[slug] detail contract floor at typical viewing zoom;
# listing thumbnails (~300-400px) downscale further at the next/image layer
# (CTK-014 §3.5.1). q75/600px primary; q70/600px fallback documented in
# plan.md D-5 if visual-quality spot-check finds ≥3 of 8 visibly soft against
# source-baseline (q85 fallback retired Session 3 — wrong direction).
_TARGET_MAX_EDGE = 600
_WEBP_QUALITY = 75

# Filename hygiene — Supabase Storage object IDs allow most chars, but we
# normalize to a tight set so the URL is predictable + collision-resistant.
_HANDLE_SAFE = re.compile(r"[^a-z0-9._-]")


def mirror(client, vendor_slug: str, product_url: str, vendor_image_url: str) -> str | None:
    """Fetch + compress + upload + return public URL. Returns None on any
    failure (network, non-200, upload error) — caller writes image_url=NULL
    and continues with the listing UPSERT per CTK-019 #55.

    Forward-write extension is `.webp` unconditionally per CTK-035 D-2 path
    cutover. Pillow exception during compression falls through to raw bytes
    at the vendor-source extension; D-2's `.webp` cutover applies on the
    happy path only — fail-soft preserves the prior raw-upload contract."""
    body = http.fetch_image(vendor_image_url)
    if body is None:
        return None

    try:
        body = _compress(body)
        ext = ".webp"
        content_type = "image/webp"
    except Exception as e:  # noqa: BLE001 — Pillow exceptions are heterogeneous
        log.info("image compression failed for %s, uploading raw: %s", vendor_image_url, e)
        ext = _extension_from_url(vendor_image_url)
        content_type = _content_type_from_extension(ext)

    handle = _handle_from_url(product_url)
    object_path = f"{vendor_slug}/{handle}{ext}"

    try:
        client.storage.from_(_BUCKET).upload(
            path=object_path,
            file=body,
            file_options={
                "content-type": content_type,
                "upsert": "true",  # idempotent re-scrape
            },
        )
    except Exception as e:  # noqa: BLE001 — Supabase SDK exceptions are heterogeneous
        log.info("image upload failed for %s: %s", object_path, e)
        return None

    return _public_url(object_path)


def _compress(body: bytes) -> bytes:
    """Resize to 600px max long edge + re-encode as WebP q75. Returns new
    bytes. Raises on Pillow decode failure — caller is responsible for
    fail-soft fall-through per arch decision #55.

    `Image.thumbnail()` is no-upscale by contract — images smaller than
    `_TARGET_MAX_EDGE` on both dimensions pass through at native size.
    Non-RGB/L modes (RGBA, P, CMYK) flatten to RGB before save; alpha is
    dropped against an implicit white background via Pillow's default
    `convert('RGB')` path."""
    img = Image.open(BytesIO(body))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((_TARGET_MAX_EDGE, _TARGET_MAX_EDGE))
    out = BytesIO()
    img.save(out, "WEBP", quality=_WEBP_QUALITY, method=6)
    return out.getvalue()


def _handle_from_url(product_url: str) -> str:
    """Extract Shopify-style handle from /products/<handle>. Falls back to
    last path segment for non-Shopify shapes."""
    path = urlparse(product_url).path or product_url
    parts = [p for p in path.split("/") if p]
    handle = parts[-1] if parts else "unknown"
    return _HANDLE_SAFE.sub("-", handle.lower()) or "unknown"


def _extension_from_url(image_url: str) -> str:
    """Best-effort extension from URL — Shopify CDN URLs carry .jpg/.png in
    the path. Default to .jpg if unrecognizable; the content-type header on
    upload is what browsers actually honor.

    Forward-write hits this path only on the Pillow-exception fail-soft
    branch in `mirror()`; happy-path forward-write hard-codes `.webp` per
    CTK-035 D-2. Backfill script (CTK-035 Session 2) reuses this helper to
    derive the pre-rewrite path for the bulk-delete pass per D-2 cutover."""
    path = urlparse(image_url).path
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.lower().endswith(ext):
            return ext
    return ".jpg"


def _content_type_from_extension(ext: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")


def _public_url(object_path: str) -> str:
    """Build the public-bucket URL. Bucket is public per arch §1.3 bucket
    bootstrap — direct CDN access without auth."""
    base = os.environ["SUPABASE_URL"].rstrip("/")
    return f"{base}/storage/v1/object/public/{_BUCKET}/{object_path}"
