"""scrapers/tests/test_images_compress.py — CTK-035 Session 1 regression tests
for images.py:_compress() helper + mirror() Pillow-exception fail-soft path.

Runnable as:
  python -m scrapers.tests.test_images_compress

No DB connection; no hosted-Supabase touch. Synthetic fixtures generated
inline via Pillow (the dep we just added). Mock supabase client captures
upload payload to verify mirror()'s fail-soft branch uploads raw bytes
without invoking _compress() output.

Coverage per plan.md table row 90:
  test_compress_large_jpeg_under_target          1500x1500 JPEG → ≤80 KB WebP, max edge ≤800
  test_compress_small_image_no_upscale           600x600 JPEG → preserved at 600x600
  test_compress_corrupt_bytes_falls_through      garbage bytes → mirror() raw-upload fail-soft
  test_compress_rgba_png_flattens_to_rgb         RGBA PNG → RGB-flattened WebP
"""

from __future__ import annotations

import sys
import types
from io import BytesIO

# Stub `supabase` so this file imports cleanly when run from a venv that
# lacks scrapers/requirements.txt. images.py doesn't import supabase
# directly, but the package's __init__ chain may pull it in via siblings.
sys.modules.setdefault(
    "supabase",
    types.SimpleNamespace(Client=object, create_client=lambda *a, **k: None),
)

from PIL import Image

from scrapers.common import images


# ─── Fixture helpers ──────────────────────────────────────────────────────────
def _make_jpeg(size: tuple[int, int]) -> bytes:
    """Make a JPEG bytes fixture with a smooth gradient — compresses
    representatively for vendor product photography (smooth coral surfaces
    + soft tank lighting), not random noise."""
    img = Image.new("RGB", size)
    pixels = img.load()
    w, h = size
    for x in range(w):
        for y in range(h):
            pixels[x, y] = (
                (x * 255) // max(w - 1, 1),
                (y * 255) // max(h - 1, 1),
                ((x + y) * 255) // max(w + h - 2, 1),
            )
    out = BytesIO()
    img.save(out, "JPEG", quality=95)
    return out.getvalue()


def _make_rgba_png(size: tuple[int, int]) -> bytes:
    """Make an RGBA PNG fixture with a transparent gradient — exercises the
    `convert('RGB')` flatten branch in `_compress()`."""
    img = Image.new("RGBA", size)
    pixels = img.load()
    w, h = size
    for x in range(w):
        for y in range(h):
            pixels[x, y] = (
                (x * 255) // max(w - 1, 1),
                (y * 255) // max(h - 1, 1),
                128,
                (x * 255) // max(w - 1, 1),  # gradient alpha
            )
    out = BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ─── Test 1: large JPEG compresses under target ──────────────────────────────
def test_compress_large_jpeg_under_target():
    """1500x1500 vendor-source JPEG → WebP at max edge ≤ 800 px and ≤ 80 KB.
    Acceptance criterion line 98: 'Forward-write images.py:mirror() produces
    WebP bytes ≤80 KB on a representative 1500x1500 vendor JPEG.'"""
    src = _make_jpeg((1500, 1500))
    out = images._compress(src)
    assert len(out) <= 80 * 1024, (
        f"compressed bytes exceeded 80 KB target: {len(out)} bytes "
        f"(source was {len(src)} bytes)"
    )
    decoded = Image.open(BytesIO(out))
    assert max(decoded.size) <= images._TARGET_MAX_EDGE, (
        f"compressed max edge exceeded {images._TARGET_MAX_EDGE} px: got {decoded.size}"
    )
    assert decoded.format == "WEBP", (
        f"expected WEBP format, got {decoded.format}"
    )


# ─── Test 2: small image preserved (thumbnail no-upscale) ────────────────────
def test_compress_small_image_no_upscale():
    """600x600 source → preserved at 600x600 in output. Pillow's `thumbnail()`
    is no-upscale by contract; the helper must not enlarge sub-target images."""
    src = _make_jpeg((600, 600))
    out = images._compress(src)
    decoded = Image.open(BytesIO(out))
    assert decoded.size == (600, 600), (
        f"thumbnail() upscaled a sub-target image: expected (600, 600), got {decoded.size}"
    )
    assert decoded.format == "WEBP"


# ─── Test 3: corrupt bytes fall through to mirror() raw-upload path ──────────
def test_compress_corrupt_bytes_falls_through():
    """Garbage bytes → `_compress()` raises → `mirror()` catches, uploads raw
    bytes at the vendor-source extension/content-type. Verifies fail-soft
    contract per arch decision #55 + CTK-035 D-3."""
    # _compress() itself raises on corrupt bytes — required precondition for
    # the fail-soft path in mirror() to fire.
    raised = False
    try:
        images._compress(b"this is definitely not an image")
    except Exception:  # noqa: BLE001 — Pillow exception types are heterogeneous
        raised = True
    assert raised, "_compress() must raise on corrupt bytes (precondition for fail-soft)"

    # Now exercise mirror()'s fail-soft branch end-to-end with a captured
    # upload payload. Mocks: http.fetch_image returns garbage bytes;
    # supabase client captures upload kwargs. Assert that the upload body
    # equals the raw garbage (NOT a _compress() output) and that the path
    # carries the vendor-source extension (.jpg, NOT .webp cutover).
    captured: dict = {}

    class _MockBucket:
        def upload(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(status_code=200)

    class _MockStorage:
        def from_(self, bucket):
            assert bucket == images._BUCKET
            return _MockBucket()

    class _MockClient:
        storage = _MockStorage()

    raw_garbage = b"this is definitely not an image"
    original_fetch = images.http.fetch_image
    original_public_url = images._public_url
    images.http.fetch_image = lambda url: raw_garbage
    images._public_url = lambda path: f"https://example.test/{path}"
    try:
        result = images.mirror(
            client=_MockClient(),
            vendor_slug="testvendor",
            product_url="https://example.test/products/test-coral",
            vendor_image_url="https://cdn.example.test/img/test-coral.jpg",
        )
    finally:
        images.http.fetch_image = original_fetch
        images._public_url = original_public_url

    assert result is not None, (
        "mirror() returned None on Pillow-exception path; fail-soft contract requires "
        "raw-upload success path to return the public URL"
    )
    assert captured.get("file") == raw_garbage, (
        f"fail-soft branch uploaded compressed (or transformed) bytes instead of raw: "
        f"got {len(captured.get('file', b''))} bytes vs raw {len(raw_garbage)}"
    )
    assert captured.get("path", "").endswith(".jpg"), (
        f"fail-soft branch did not preserve vendor-source extension: "
        f"path={captured.get('path')!r}"
    )
    assert captured.get("file_options", {}).get("content-type") == "image/jpeg", (
        f"fail-soft branch did not preserve vendor-source content-type: "
        f"got {captured.get('file_options', {}).get('content-type')!r}"
    )


# ─── Test 4: RGBA PNG flattens to RGB cleanly ────────────────────────────────
def test_compress_rgba_png_flattens_to_rgb():
    """RGBA PNG (transparent gradient) → `_compress()` flattens to RGB and
    encodes WebP successfully. Verifies the `convert('RGB')` branch handles
    non-RGB/L modes without raising."""
    src = _make_rgba_png((400, 400))
    out = images._compress(src)
    decoded = Image.open(BytesIO(out))
    assert decoded.format == "WEBP", (
        f"expected WEBP format, got {decoded.format}"
    )
    assert decoded.mode == "RGB", (
        f"RGBA flatten failed: expected RGB output mode, got {decoded.mode}"
    )
    assert decoded.size == (400, 400), (
        f"sub-target RGBA image was resized: expected (400, 400), got {decoded.size}"
    )


# ─── Test runner ──────────────────────────────────────────────────────────────
TESTS = [
    test_compress_large_jpeg_under_target,
    test_compress_small_image_no_upscale,
    test_compress_corrupt_bytes_falls_through,
    test_compress_rgba_png_flattens_to_rgb,
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
        except Exception as e:  # noqa: BLE001 — surface the unexpected exception type
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed (total {len(TESTS)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
