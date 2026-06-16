"""CTK-164 A-path — tests for the Ken Burns render primitive + framing.

Pure tests (no ffmpeg) cover the filter/arg assembly and the 9:16 compose. One
ffmpeg-gated integration smoke renders a real frame to a valid MP4 and checks
the duration. Run:

  python -m pytest scrapers/tests/test_video.py
"""

from __future__ import annotations

import io

from PIL import Image

from scrapers.common import video
from scrapers.common.video import MotionSpec


def _png_bytes(width: int, height: int, colour=(180, 40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, "PNG")
    return buf.getvalue()


# --- pure: MotionSpec + filter/arg assembly ---------------------------------


def test_motionspec_total_frames():
    assert MotionSpec(duration_sec=7.0, fps=30).total_frames == 210
    assert MotionSpec(duration_sec=0.0, fps=30).total_frames == 1  # floor at 1


def test_zoompan_filter_zoom_in():
    f = video.build_zoompan_filter(MotionSpec(), prescale=8)
    assert "scale=iw*8:ih*8" in f          # anti-jitter prescale
    assert "zoompan=" in f
    assert "min(zoom+" in f                 # ramps up
    assert "d=210" in f                     # 7s * 30fps
    assert f"s={video.REEL_W}x{video.REEL_H}" in f
    assert "x='iw/2-(iw/zoom/2)'" in f      # centered


def test_zoompan_filter_zoom_out():
    f = video.build_zoompan_filter(MotionSpec(direction="zoom-out"))
    assert "max(zoom-" in f                 # ramps down


def test_ffmpeg_args_shape():
    args = video.build_ffmpeg_args("frame.png", "out.mp4", MotionSpec())
    assert args[0] == video._FFMPEG
    assert "frame.png" in args and args[-1] == "out.mp4"
    assert "-pix_fmt" in args and "yuv420p" in args   # IG-compatible
    assert "libx264" in args
    assert "+faststart" in args


# --- pure-ish: 9:16 compose (Pillow, no ffmpeg) -----------------------------


def test_compose_dims_from_landscape():
    frame = video.compose_9x16_blurred_fill(_png_bytes(600, 400))
    assert frame.size == (video.REEL_W, video.REEL_H)
    assert frame.mode == "RGB"


def test_compose_dims_from_portrait():
    frame = video.compose_9x16_blurred_fill(_png_bytes(400, 600))
    assert frame.size == (video.REEL_W, video.REEL_H)


def test_compose_dims_from_square():
    frame = video.compose_9x16_blurred_fill(_png_bytes(500, 500))
    assert frame.size == (video.REEL_W, video.REEL_H)


# --- ffmpeg-gated integration smoke -----------------------------------------


def test_render_kenburns_produces_valid_mp4(tmp_path):
    frame = video.compose_9x16_blurred_fill(_png_bytes(600, 400))
    frame_path = tmp_path / "frame.png"
    frame.save(frame_path, "PNG")
    out_path = tmp_path / "reel.mp4"

    result = video.render_kenburns(frame_path, out_path, motion_spec=MotionSpec(duration_sec=7.0, fps=30))

    assert result.exists()
    assert result.stat().st_size > 0
    duration = video.probe_duration(out_path)
    assert 6.5 <= duration <= 7.5, f"expected ~7s, got {duration}s"
