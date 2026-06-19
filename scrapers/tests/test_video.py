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


def test_encode_args_pins_profile_level_gop():
    # The cross-producer concat precondition: profile/level/GOP are pinned (not
    # libx264-default-derived) so the zoompan path and the image2 path emit
    # byte-identical SPS/PPS. -g tracks fps (one keyframe/sec).
    args = video._encode_args("out.mp4", 30)
    assert args[args.index("-profile:v") + 1] == "high"
    assert args[args.index("-level") + 1] == "4.0"
    assert args[args.index("-g") + 1] == "30"
    assert args[-1] == "out.mp4"


def test_kenburns_and_sequence_share_encode_tail():
    # Both producers route through _encode_args — the same OUTPUT tail (everything
    # from -c:v onward) guarantees concat-compatible clips.
    tail = video._encode_args("x.mp4", 30)
    kb = video.build_ffmpeg_args("f.png", "x.mp4", MotionSpec(fps=30))
    assert kb[-len(tail):] == tail


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


# --- B-path: DATA_CARD_MOTION preset + concat_clips -------------------------


def test_data_card_motion_preset():
    m = video.DATA_CARD_MOTION
    # Barely-there zoom — legibility budget, NOT the A-path 1.0->1.15 travel.
    assert (m.zoom_start, m.zoom_end) == (1.0, 1.02)
    # Shares duration/fps with the A-path default so DATA_CARD_MOTION clips have
    # identical codec params and concat_clips can stream-copy them.
    assert (m.duration_sec, m.fps) == (video.DEFAULT_MOTION.duration_sec, video.DEFAULT_MOTION.fps)


def test_concat_clips_joins_to_one_mp4(tmp_path):
    # Two short DATA_CARD_MOTION clips (identical codec params) -> one mp4 whose
    # duration is the sum, via the concat demuxer + stream copy.
    short = MotionSpec(duration_sec=1.0, fps=video.DATA_CARD_MOTION.fps,
                       zoom_start=video.DATA_CARD_MOTION.zoom_start,
                       zoom_end=video.DATA_CARD_MOTION.zoom_end)
    clips = []
    for i, colour in enumerate([(30, 94, 32), (245, 241, 234)]):
        frame_path = tmp_path / f"frame{i}.png"
        Image.new("RGB", (video.REEL_W, video.REEL_H), colour).save(frame_path, "PNG")
        clip = tmp_path / f"clip{i}.mp4"
        video.render_kenburns(frame_path, clip, motion_spec=short)
        clips.append(clip)

    out_path = tmp_path / "joined.mp4"
    result = video.concat_clips(clips, out_path)

    assert result.exists() and result.stat().st_size > 0
    duration = video.probe_duration(out_path)
    assert 1.7 <= duration <= 2.3, f"expected ~2s joined, got {duration}s"


def test_concat_clips_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        video.concat_clips([], "out.mp4")


# --- PB-2: render_sequence (image2 demuxer) + cross-producer concat -----------


def _frame_seq(tmp_path, n: int, fps: int) -> list:
    """n distinct PNG frames at REEL dims (a faux content animation — the colour
    shifts each frame) named arbitrarily, to prove render_sequence does not depend
    on the caller's frame naming."""
    paths = []
    for i in range(n):
        p = tmp_path / f"anim-{i}.png"
        Image.new("RGB", (video.REEL_W, video.REEL_H), (20 + i * 3, 94, 32)).save(p, "PNG")
        paths.append(p)
    return paths


def test_render_sequence_produces_valid_mp4(tmp_path):
    fps = 30
    frames = _frame_seq(tmp_path, n=fps, fps=fps)   # 30 frames @ 30fps -> ~1s
    out_path = tmp_path / "seq.mp4"

    result = video.render_sequence(frames, out_path, fps=fps)

    assert result.exists() and result.stat().st_size > 0
    duration = video.probe_duration(out_path)
    assert 0.8 <= duration <= 1.2, f"expected ~1s, got {duration}s"


def test_render_sequence_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        video.render_sequence([], "out.mp4")


def test_cross_producer_concat_joins_clean(tmp_path):
    # THE PB-2/PB-5 crux that did not exist before: a render_sequence clip (image2
    # input) concatenated with a render_kenburns clip (zoompan input). -c copy only
    # works because _encode_args pins SPS/PPS identically across both paths; this
    # test fails LOUD if a future edit diverges the two tails.
    fps = video.DATA_CARD_MOTION.fps

    seq_frames = _frame_seq(tmp_path, n=fps, fps=fps)   # ~1s sequence clip
    seq_clip = tmp_path / "seq.mp4"
    video.render_sequence(seq_frames, seq_clip, fps=fps)

    kb_frame = tmp_path / "kb.png"
    Image.new("RGB", (video.REEL_W, video.REEL_H), (245, 241, 234)).save(kb_frame, "PNG")
    kb_clip = tmp_path / "kb.mp4"
    short_kb = MotionSpec(duration_sec=1.0, fps=fps,
                          zoom_start=video.DATA_CARD_MOTION.zoom_start,
                          zoom_end=video.DATA_CARD_MOTION.zoom_end)
    video.render_kenburns(kb_frame, kb_clip, motion_spec=short_kb)

    out_path = tmp_path / "joined.mp4"
    result = video.concat_clips([seq_clip, kb_clip], out_path)

    assert result.exists() and result.stat().st_size > 0
    duration = video.probe_duration(out_path)
    assert 1.7 <= duration <= 2.3, f"expected ~2s cross-producer join, got {duration}s"
