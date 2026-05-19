"""Image-pipeline integration per CTK-019 calls #51-#56 + CTK-035 compression
cutover + CTK-036 cut-2 storage-backend swap. Mirrors a vendor's image to the
Cloudflare R2 `coralticker-images` bucket via the S3-compatible API; returns
the public URL on success or None on failure. Synchronous, 1-attempt, image-
only failure does NOT fail the row scrape (CTK-019 #55).

Forward-write per CTK-035 D-2 + D-3: compress to WebP @ 600px max long edge,
q75, before upload; bucket key is `{vendor_slug}/{handle}.webp`. Pillow
exception during compression falls through to raw-bytes upload at the
vendor-source extension/content-type — fail-soft semantics per arch
decision #55.

CTK-036 cut-2 (Q-C minimal SDK swap, 2026-05-15): replaced Supabase Storage
SDK upload + Supabase public-URL synthesis with boto3 S3-compat PUT against
R2 endpoint + custom-domain URL synthesis. _compress() / _handle_from_url() /
_extension_from_url() / _content_type_from_extension() unchanged. mirror()
signature dropped its `client` param (Supabase client no longer needed in
this module post-swap); diff.py persist_phase_b updated in the same commit.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from io import BytesIO
from urllib.parse import urlparse

import boto3
from PIL import Image

from scrapers.common import http

log = logging.getLogger(__name__)


# CTK-035 compression knobs (re-tuned Session 3). 600px max long edge stays
# above site.md /coral/[slug] detail contract floor at typical viewing zoom;
# listing thumbnails (~300-400px) downscale further at the next/image layer
# (CTK-014 §3.5.1). q75/600px primary; q70/600px fallback documented in
# plan.md D-5 if visual-quality spot-check finds ≥3 of 8 visibly soft against
# source-baseline (q85 fallback retired Session 3 — wrong direction).
_TARGET_MAX_EDGE = 600
_WEBP_QUALITY = 75

# Filename hygiene — R2 object keys allow most chars, but we normalize to a
# tight set so the URL is predictable + collision-resistant.
_HANDLE_SAFE = re.compile(r"[^a-z0-9._-]")

# CTK-036 cut-2 — public-URL host. Custom domain bound at R2 Settings →
# Custom Domains 2026-05-15 per Q-A; Cloudflare Workers route auto-created.
_PUBLIC_HOST = "https://images.coralticker.com"

# Lazy module-level boto3 client. Built on first mirror() call; subsequent
# calls reuse. Thread-safe under Phase B's single-threaded loop in diff.py;
# scripts/backfill_supabase_to_r2.py (cut-3) uses ThreadPoolExecutor so the
# init guard exists for that consumer.
_S3_CLIENT = None
_S3_CLIENT_LOCK = threading.Lock()


def _get_s3_client():
    """Lazy-init the boto3 S3 client against R2. Reads R2_ACCOUNT_ID +
    R2_ACCESS_KEY_ID + R2_SECRET_ACCESS_KEY from env at first call. Region
    is hard-coded to 'auto' per R2's regionless model. Tests can monkey-
    patch the module-level _S3_CLIENT directly to inject a mock."""
    global _S3_CLIENT
    if _S3_CLIENT is not None:
        return _S3_CLIENT
    with _S3_CLIENT_LOCK:
        if _S3_CLIENT is not None:
            return _S3_CLIENT
        account_id = os.environ["R2_ACCOUNT_ID"]
        _S3_CLIENT = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
    return _S3_CLIENT


def mirror(vendor_slug: str, product_url: str, vendor_image_url: str) -> str | None:
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
    object_key = f"{vendor_slug}/{handle}{ext}"

    try:
        _get_s3_client().put_object(
            Bucket=os.environ["R2_BUCKET_NAME"],
            Key=object_key,
            Body=body,
            ContentType=content_type,
        )
    except Exception as e:  # noqa: BLE001 — botocore exceptions are heterogeneous
        log.info("image upload failed for %s: %s", object_key, e)
        return None

    return _public_url(object_key)


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
    CTK-035 D-2."""
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


def _public_url(object_key: str) -> str:
    """Build the public URL via the R2 custom domain (CTK-036 Q-A).
    images.coralticker.com is bound at R2 Settings → Custom Domains; reads
    are anonymous and route through the auto-created Cloudflare Workers
    route. Object keys are bucket-relative."""
    return f"{_PUBLIC_HOST}/{object_key}"
