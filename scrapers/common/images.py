"""Image-pipeline integration per CTK-019 calls #51-#56. Mirrors a vendor's
image to the listing-images Supabase Storage bucket; returns the public URL
on success or None on failure. Synchronous, 1-attempt, image-only failure
does NOT fail the row scrape (CTK-019 #55).
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlparse

from scrapers.common import http

log = logging.getLogger(__name__)


_BUCKET = "listing-images"

# Filename hygiene — Supabase Storage object IDs allow most chars, but we
# normalize to a tight set so the URL is predictable + collision-resistant.
_HANDLE_SAFE = re.compile(r"[^a-z0-9._-]")


def mirror(client, vendor_slug: str, product_url: str, vendor_image_url: str) -> str | None:
    """Fetch + upload + return public URL. Returns None on any failure
    (network, non-200, upload error) — caller writes image_url=NULL and
    continues with the listing UPSERT per CTK-019 #55."""
    body = http.fetch_image(vendor_image_url)
    if body is None:
        return None

    handle = _handle_from_url(product_url)
    ext = _extension_from_url(vendor_image_url)
    object_path = f"{vendor_slug}/{handle}{ext}"

    try:
        client.storage.from_(_BUCKET).upload(
            path=object_path,
            file=body,
            file_options={
                "content-type": _content_type_from_extension(ext),
                "upsert": "true",  # idempotent re-scrape
            },
        )
    except Exception as e:  # noqa: BLE001 — Supabase SDK exceptions are heterogeneous
        log.info("image upload failed for %s: %s", object_path, e)
        return None

    return _public_url(object_path)


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
    upload is what browsers actually honor."""
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
