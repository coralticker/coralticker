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
import shutil
import subprocess
import tempfile
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

# B-path (data-card motion) preset — a barely-there zoom. The A-path default
# pushes 1.0 -> 1.15 because a photo tolerates the travel; a data card's whole
# value is its legible text, so the zoom is a near-still 1.0 -> 1.02 (life, not
# movement). Past ~1.03 the type drifts enough to read as a wobble on a card the
# viewer is trying to READ. Same duration/fps as A-path so DATA_CARD_MOTION clips
# share codec params and concat_clips can stream-copy them.
DATA_CARD_MOTION = MotionSpec(zoom_start=1.0, zoom_end=1.02)


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


def _encode_args(out_path: str | Path, fps: int) -> list[str]:
    """The shared OUTPUT-side ffmpeg argv tail for EVERY clip producer — the
    zoompan-input path (render_kenburns / build_ffmpeg_args) and the image2-input
    path (render_sequence) both route through here.

    Why it is shared and why the H.264 knobs are pinned: concat_clips joins clips
    with -c copy (stream copy, no re-encode), whose precondition is byte-identical
    codec params across every input — including the SPS/PPS NAL headers. SPS/PPS is
    a function of profile + level + resolution + pix_fmt; if the zoompan path and
    the image2 path encode with different (or libx264-default-derived) profile/level,
    a count-up cover slide (render_sequence) concatenated with a Ken Burns inner
    (render_kenburns) produces a join the demuxer accepts but that decodes corrupt
    downstream of the seam. Pinning -profile:v / -level / -g makes both paths emit
    the same headers, so the cross-producer concat is sound. -g (GOP) is pinned to
    fps (one keyframe/sec) so the GOP structure is deterministic on both paths too.
    Resolution is the caller's contract (both produce 1080x1920); pix_fmt is yuv420p
    for IG compatibility. Do NOT diverge these between the two callers."""
    return [
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level", "4.0",
        "-pix_fmt", "yuv420p",
        "-g", str(fps),
        "-r", str(fps),
        "-movflags", "+faststart",
        str(out_path),
    ]


def build_ffmpeg_args(frame_path: str | Path, out_path: str | Path, spec: MotionSpec) -> list[str]:
    """The full ffmpeg argv for render_kenburns. Pure (no execution) so the
    arg assembly is unit-testable without encoding. Shares _encode_args with
    render_sequence so the two producers' clips concat-join clean (PB-5)."""
    return [
        _FFMPEG,
        "-y",
        "-i", str(frame_path),
        "-vf", build_zoompan_filter(spec),
        *_encode_args(out_path, spec.fps),
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


def concat_clips(clips: list[str | Path], out_path: str | Path) -> Path:
    """Join MP4 clips into one via ffmpeg's concat demuxer with stream copy
    (-f concat ... -c copy) — no re-encode, no generation loss, the F7/F9
    card-sequence-as-reel join (PB-5).

    PRECONDITION: every clip shares identical codec params (dimensions, fps,
    h264 profile, pix_fmt, SPS/PPS). Guaranteed when all clips come from
    render_kenburns with the SAME MotionSpec — e.g. DATA_CARD_MOTION at
    1080x1920/30fps. If a param ever diverges, the demuxer emits a corrupt join;
    the fallback is a filter_complex re-encode (NOT built — no consumer needs it).

    Raises on a non-zero ffmpeg exit (loud-failure) and on an empty clip list."""
    clips = [Path(c) for c in clips]
    if not clips:
        raise ValueError("concat_clips: no clips to join")

    # The concat demuxer reads a list file of `file '<path>'` lines. Single quotes
    # in a path are escaped per ffmpeg's rule ('\'' ). -safe 0 permits absolute paths.
    listing = "\n".join(
        "file '{}'".format(str(c.resolve()).replace("'", "'\\''")) for c in clips
    )
    list_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            list_path = f.name   # set BEFORE write so a write failure still cleans up
            f.write(listing + "\n")
        args = [
            _FFMPEG, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path),
        ]
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed (exit {proc.returncode}) for {out_path}:\n"
                f"{proc.stderr[-2000:]}"
            )
    finally:
        if list_path is not None:
            Path(list_path).unlink(missing_ok=True)
    return Path(out_path)


def render_sequence(
    frames: list[str | Path],
    out_path: str | Path,
    *,
    fps: int = DEFAULT_MOTION.fps,
) -> Path:
    """Encode an ordered PNG sequence into a looping MP4 via ffmpeg's image2
    demuxer (-framerate {fps} -i frame_%05d.png), the SECOND encode entry point
    (PB-2). render_kenburns animates the CAMERA over one still; render_sequence
    plays back a sequence where the CONTENT itself differs frame to frame — a
    count-up tick, an em-dash reveal, a strike-draw. The frame-by-frame content
    animation lives upstream (the card's JS seek function, captured by
    rasterize_sequence); this primitive is content-blind — frames + fps in, MP4
    out, no easing/count-up logic here and NO ffmpeg motion filter (INV-06 PB-2:
    MotionSpec / filters stay camera-only; content motion is the Pillow-drift
    reject's resolution — capture the real CSS animation, never re-implement it).

    Shares _encode_args with render_kenburns so a render_sequence clip and a
    render_kenburns clip carry byte-identical SPS/PPS and concat_clips stream-copies
    them into one reel (a count-up cover + Ken Burns inners — PB-5).

    frames is an ordered list of PNG paths with ANY names: the image2 %05d pattern
    is satisfied by staging canonically-named symlinks in a temp dir, so the input
    naming is an implementation detail here, never a caller contract (keeps
    rasterize_sequence free to name its output for human debug). Raises on an empty
    sequence or a non-zero ffmpeg exit (loud-failure)."""
    frames = [Path(f) for f in frames]
    if not frames:
        raise ValueError("render_sequence: no frames to encode")

    stage = Path(tempfile.mkdtemp(prefix="ct-seq-"))
    try:
        for i, frame in enumerate(frames):
            (stage / f"frame_{i:05d}.png").symlink_to(frame.resolve())
        args = [
            _FFMPEG, "-y",
            "-framerate", str(fps),
            "-i", str(stage / "frame_%05d.png"),
            *_encode_args(out_path, fps),
        ]
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg sequence encode failed (exit {proc.returncode}) for {out_path}:\n"
                f"{proc.stderr[-2000:]}"
            )
    finally:
        shutil.rmtree(stage, ignore_errors=True)
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
