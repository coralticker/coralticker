"""CTK-164 A-path — Ken Burns video render: the shared encode primitive +
the A-path 9:16 framing.

Two layers, deliberately split (the /lead-architect boundary, routed before
CTK-163 scaffolds its TikTok/YT path):

  render_kenburns(frame_path, out_path, *, motion_spec)
      The consumer-agnostic encode primitive. Takes ONE pre-composed frame
      (already at the output dimensions) and applies a slow Ken Burns
      pan/zoom -> looping vertical MP4 via ffmpeg's zoompan filter. Knows
      nothing about vendor photos, cards, or data rows — A-path (clean photo),
      CTK-163 (TikTok/YT), and the later B-path (data-card motion) all feed it
      their own composed frame.

  compose_9x16_blurred_fill(image_bytes)
      A-path-specific framing. Fits an arbitrary-aspect mirrored vendor photo
      into a 1080x1920 frame: the real photo sits at native scale in a centered
      band over a blurred-stretched copy of itself (no letterbox bars, no
      distortion, no crop loss on wide coral shots). Canon-clean — it is the
      same real animal, no CoralTicker branding and no synthetic content baked
      on (CTK-157 §5 reshare canon; branding-guide.md:129 image-honesty).

ffmpeg is the bundled-pip binary from imageio-ffmpeg (zero-touch local + CI; no
system install to chase). We call it directly via subprocess with the zoompan
filter — moviepy would only wrap the same binary and add an object graph for no
gain on a one-filter pan.

Anti-jitter: zoompan snaps its crop window to integer pixels, which shakes a
slow zoom on a raw still. The fix is to upscale the input frame PRESCALE-fold
before zoompan so the per-frame zoom increment is sub-pixel, then let zoompan's
s= downscale to the final dimensions.

Source-resolution note: the A-path frame is built from the 600px-max WebP
mirror (the vendor original is not retained). The foreground band therefore
upscales ~1.8x to 1080 wide; the shallow default zoom (1.0 -> 1.15) limits
further softening. If the first batch reads too soft, the escalation is
re-fetching full-res from product_url (a follow-up, not this slice).
"""

from __future__ import annotations

import io
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageFilter, ImageOps

# Output canvas — IG Reels / vertical 9:16.
REEL_W = 1080
REEL_H = 1920

# Anti-jitter upscale factor applied before zoompan (Q3, /lead-backend-confirmed).
PRESCALE = 8

# Background blur radius for the 9:16 fill band. Heavy enough that the upscaled
# background reads as soft colour wash, not a recognisable second image.
_BG_BLUR_RADIUS = 40

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# ffmpeg -i <file> with no output exits non-zero by design but still prints the
# stream header (incl. Duration:) to stderr — we parse that, not exit code.
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class MotionSpec:
    """The motion parameters for one render. Consumer-agnostic so CTK-163 /
    B-path can reuse render_kenburns with their own pan/zoom shapes.

    direction:
      "zoom-in"  — start at zoom_start, ramp to zoom_end (A-path default).
      "zoom-out" — start at zoom_end, ramp down to zoom_start.
    (pan-* directions are reserved for the later consumers; A-path is center
    zoom only.)
    """

    duration_sec: float = 7.0
    fps: int = 30
    zoom_start: float = 1.0
    zoom_end: float = 1.15
    direction: str = "zoom-in"

    @property
    def total_frames(self) -> int:
        return max(1, round(self.duration_sec * self.fps))


DEFAULT_MOTION = MotionSpec()


# ---------------------------------------------------------------------------
# Pure arg/filter construction — unit-driven, no ffmpeg call, no encode.
# ---------------------------------------------------------------------------


def build_zoompan_filter(
    spec: MotionSpec,
    *,
    prescale: int = PRESCALE,
    width: int = REEL_W,
    height: int = REEL_H,
) -> str:
    """The ffmpeg -vf filtergraph for a center Ken Burns zoom on a single frame.

    Upscales prescale-fold first (sub-pixel zoom increment, anti-jitter), then
    zoompan ramps the zoom across total_frames and downscales to width x height.
    """
    frames = spec.total_frames
    if spec.direction == "zoom-out":
        step = (spec.zoom_end - spec.zoom_start) / frames
        z_expr = f"if(eq(on,0),{spec.zoom_end:.6f},max(zoom-{step:.8f},{spec.zoom_start:.6f}))"
    else:  # zoom-in (default)
        step = (spec.zoom_end - spec.zoom_start) / frames
        z_expr = f"if(eq(on,0),{spec.zoom_start:.6f},min(zoom+{step:.8f},{spec.zoom_end:.6f}))"

    # Center the zoom: x/y track the shrinking crop window around the midpoint.
    return (
        f"scale=iw*{prescale}:ih*{prescale},"
        f"zoompan=z='{z_expr}'"
        f":d={frames}:s={width}x{height}:fps={spec.fps}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    )


def build_ffmpeg_args(frame_path: str | Path, out_path: str | Path, spec: MotionSpec) -> list[str]:
    """The full ffmpeg argv for render_kenburns. Pure (no execution) so the
    arg assembly is unit-testable without encoding."""
    return [
        _FFMPEG,
        "-y",
        "-i", str(frame_path),
        "-vf", build_zoompan_filter(spec),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(spec.fps),
        "-movflags", "+faststart",
        str(out_path),
    ]


# ---------------------------------------------------------------------------
# A-path framing — Pillow compose, no ffmpeg.
# ---------------------------------------------------------------------------


def compose_9x16_blurred_fill(
    image_bytes: bytes,
    *,
    width: int = REEL_W,
    height: int = REEL_H,
    blur_radius: int = _BG_BLUR_RADIUS,
) -> Image.Image:
    """Fit an arbitrary-aspect photo into a width x height frame: the real photo
    centered at contain-scale over a blurred cover-fill of itself. Returns an
    RGB PIL image at exactly (width, height)."""
    src = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Background: cover-fill the whole canvas (crop overflow), then blur. fit()
    # upscales as needed — softness is invisible under the blur.
    background = ImageOps.fit(src, (width, height), method=Image.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(blur_radius))

    # Foreground: contain within the canvas (no crop), allowing upscale so the
    # photo fills the width band. thumbnail() refuses upscale, so resize by an
    # explicit contain-scale.
    scale = min(width / src.width, height / src.height)
    fg_w, fg_h = max(1, round(src.width * scale)), max(1, round(src.height * scale))
    foreground = src.resize((fg_w, fg_h), Image.LANCZOS)

    background.paste(foreground, ((width - fg_w) // 2, (height - fg_h) // 2))
    return background


# ---------------------------------------------------------------------------
# Encode primitive — the one ffmpeg call. Loud-fail on non-zero exit.
# ---------------------------------------------------------------------------


def render_kenburns(
    frame_path: str | Path,
    out_path: str | Path,
    *,
    motion_spec: MotionSpec = DEFAULT_MOTION,
) -> Path:
    """Render one pre-composed frame to a Ken Burns MP4. Raises on a non-zero
    ffmpeg exit (loud-failure) with the tail of stderr for the 11pm debug."""
    args = build_ffmpeg_args(frame_path, out_path, motion_spec)
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg render failed (exit {proc.returncode}) for {out_path}:\n"
            f"{proc.stderr[-2000:]}"
        )
    return Path(out_path)


def probe_duration(path: str | Path) -> float:
    """Seconds of an MP4, parsed from ffmpeg -i stderr (ffprobe is not bundled
    with imageio-ffmpeg). ffmpeg -i exits non-zero with no output target — we
    parse stderr regardless of exit code."""
    proc = subprocess.run([_FFMPEG, "-i", str(path)], capture_output=True, text=True)
    m = _DURATION_RE.search(proc.stderr)
    if not m:
        raise RuntimeError(f"could not parse Duration from ffmpeg -i:\n{proc.stderr[-1000:]}")
    hours, minutes, seconds = m.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
