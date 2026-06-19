"""CTK-164 B-path — data-card HTML assembly + the INV-01 field-driven data-row
adapter (the PB-3 gate).

The B-path renders owned, photo-less data cards (no vendor photo — CTK-157 §5 /
CTK-159 D-4 surface-B canon). The card's em-dash data row is INV-01-bound: it
must render the SAME logical content as the web <DataRow> and the email/Discord
text channel. INV-01 binds the OUTPUT SHAPE across the language boundary, so the
card is a channel ADAPTER — it builds per-field HTML (bold Plex Sans label / Plex
Mono value / forest em-dash separators) from the SAME `fields` list that
data_row.format_data_row renders to flat text, and a parity test strips the card
row HTML back to text and asserts byte-equality with format_data_row(fields, now).
NOT a flat-string inject, NOT a hand-rolled format — the field list is the single
source, two renderers (flat text + card HTML) pinned to each other by the test.

`format_data_row_html` mirrors data_row._format_value's discriminated-union
branching so the two stay in lockstep; the parity test is the drift guard. The
card pipeline: assemble HTML (this module) -> rasterize.py (html->png) ->
video.py render_kenburns with DATA_CARD_MOTION (png->mp4).

The card TEMPLATE (card_templates/) is authored from /designer's frame
byte-structure (the source of truth) with the dynamic regions tokenized; re-sync
on a /designer revision.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from scrapers.common import rasterize, video
from scrapers.tools.data_row import format_relative_time

_TEMPLATE_DIR = Path(__file__).resolve().parent / "card_templates"

# Field separator — space + em-dash (U+2014) + space. Byte-identical to
# data_row.format_data_row's join and the /designer frame's .sep; the INV-01
# parity test enforces it.
_SEP_HTML = '<span class="sep"> — </span>'


def _esc(text: str) -> str:
    """Escape &<> for HTML text content (quotes left alone — they are valid in a
    text node and BeautifulSoup.get_text in the parity test unescapes &amp; etc.,
    so escape + strip round-trips back to format_data_row's raw text)."""
    return html.escape(str(text), quote=False)


def _value_html(value, now: datetime) -> str:
    """Per-field VALUE HTML, mirroring data_row._format_value's union branches.
    Each branch's text content (tags stripped) must equal _format_value's text so
    the row parity holds. price-drop-new / vendor-markdown split into two styled
    spans whose text is "old new" (space-joined) — matching _format_value."""
    if isinstance(value, str):
        return f'<span class="val">{_esc(value)}</span>'
    kind = value["kind"]
    if kind == "relative-time":
        return f'<span class="val">{_esc(format_relative_time(value["timestamp"], now))}</span>'
    if kind in ("price-drop-new", "vendor-markdown"):
        # Struck old value + forest-bold new value (.row .struck / .row .new); the
        # literal space between the spans reproduces _format_value's "old new" text.
        return (
            f'<span class="struck">{_esc(value["oldValue"])}</span> '
            f'<span class="new">{_esc(value["newValue"])}</span>'
        )
    if kind == "italic":
        # Scientific-binomial carve-out (the sole sanctioned italic; .row em).
        # Latent in v1 — no field carries a binomial now that Lineage. is dropped —
        # but kept defensively so a future binomial-bearing field renders correctly.
        return f'<span class="val"><em>{_esc(value["value"])}</em></span>'
    # 'invalidated' is intentionally NOT handled: B-path posts ACTIVE listings only,
    # and .row .invalid is deliberately absent from the frames. An invalidated/OOS
    # value reaching a card is a contract violation -> fail loud.
    raise ValueError(f"format_data_row_html: unhandled or card-forbidden value kind {kind!r}")


def format_data_row_html(fields: list[dict], now: datetime) -> str:
    """The INV-01 card adapter: render a DataRowField list to the card's em-dash
    data-row HTML. Stripping this to text (the parity test) yields exactly
    data_row.format_data_row(fields, now). Each field is `Label.` (bold) + a
    literal space + the value HTML; fields joined by the forest em-dash sep."""
    parts = [
        f'<span class="lab">{_esc(field["label"])}.</span> {_value_html(field["value"], now)}'
        for field in fields
    ]
    return _SEP_HTML.join(parts)


def _fill(template_name: str, **tokens: str) -> str:
    """Load a card template and substitute {{TOKEN}} placeholders. The template is
    /designer's frame byte-structure (card_templates/, source of truth); only the
    tokenized dynamic regions change. .replace (not .format) — the CSS is full of
    literal braces."""
    html_doc = (_TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    for key, value in tokens.items():
        html_doc = html_doc.replace("{{" + key + "}}", value)
    return html_doc


def _lead_html(name: str, vendor: str, event_phrase: str) -> str:
    """Inner-card lead line: "<b>{name}</b> {event_phrase} at {vendor}." —
    event_phrase is 'listed' or 'back in stock' (the Vendor rides the lead, not the
    data row, per the D-4 contract). Restocks read 'back in stock', never 'Back.'."""
    return f'<span class="name">{_esc(name)}</span> {_esc(event_phrase)} at {_esc(vendor)}.'


def render_f8_card_html(*, name: str, pct: int, fields: list[dict], now: datetime) -> str:
    """Assemble the F8 superlative card HTML: inject the coral name + drop percent
    into the stat line and the INV-01 data row into the .row. Returns a full HTML
    document ready for rasterize."""
    return _fill(
        "reel-frame-f8-superlative.html",
        STAT_NAME=_esc(name),
        STAT_PCT=str(pct),
        DATA_ROW=format_data_row_html(fields, now),
    )


def render_cover_html(template_name: str, stat_html: str) -> str:
    """A carousel COVER frame (stat-only, no data row). stat_html is the prebuilt
    .stat inner markup (the caller owns the brand copy + inline spans).

    NOTE: superseded by render_kinetic_carousel (CTK-173) — prune candidate. No prod
    caller post-repoint; retained only as a pure-builder unit (test_f7_cover_and_inner_builders
    + the static templates' skeleton-drift pairs). Prune is non-contained (the
    skeleton pairs + the mixed builder test couple it) — tracked in open-items."""
    return _fill(template_name, STAT_HTML=stat_html)


def render_inner_html(template_name: str, lead_html: str, fields: list[dict], now: datetime) -> str:
    """A carousel INNER frame (lead + INV-01 data row). lead_html is prebuilt
    (_lead_html); the row is the field-driven adapter output.

    NOTE: superseded by render_kinetic_carousel (CTK-173) — prune candidate (see
    render_cover_html). No prod caller post-repoint; tracked in open-items."""
    return _fill(template_name, LEAD_HTML=lead_html, DATA_ROW=format_data_row_html(fields, now))


def render_carousel(
    *,
    cover_html: str,
    inner_htmls: list[str],
    now: datetime,
    out_path: str | Path,
    work_dir: str | Path | None = None,
    motion=video.DATA_CARD_MOTION,
) -> Path:
    """Cover-rides-the-reel (PB-5): rasterize + Ken Burns each frame (cover FIRST,
    then inners in order), then concat_clips them into one reel. All clips share
    DATA_CARD_MOTION so the concat demuxer stream-copies (no re-encode). Returns
    out_path; intermediate PNGs/clips land in work_dir for the 11pm debug.

    NOTE: superseded by render_kinetic_carousel (CTK-173) — prune candidate. F7/F9
    moved to the kinetic (count-up/reveal) path; this static-carousel primitive has
    no prod caller post-repoint. Tracked in open-items (prune is non-contained)."""
    out_path = Path(out_path)
    work_dir = Path(work_dir) if work_dir else out_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    frames = [("cover", cover_html)] + [(f"inner{i}", h) for i, h in enumerate(inner_htmls)]
    clips: list[Path] = []
    for label, html_doc in frames:
        png = work_dir / f"{out_path.stem}-{label}.png"
        clip = work_dir / f"{out_path.stem}-{label}.mp4"
        rasterize.rasterize_html(html_doc, png)
        video.render_kenburns(png, clip, motion_spec=motion)
        clips.append(clip)
    video.concat_clips(clips, out_path)
    return out_path


# F7 cover copy register — /brand-manager cover-stat lock (branding-guide.md
# §"IG data-post copy" + CTK-161 rev2 L177-179). The cover names exactly what the
# inners contain, picked by the event COMPOSITION over the FULL window population
# (not the sample): all-arrivals -> "new arrivals", all-restocks -> "back in
# stock", mixed -> "drops". {count} is the TRUE full-window count (the honest-
# count guard, rev2 L182), never the sample size.
_F7_COVER_COPY = {
    "all-arrivals": "new arrivals this week.",
    "all-restocks": "back in stock this week.",
    "mixed": "drops this week.",
}


def f7_cover_stat_html(count: int, composition: str) -> str:
    """F7 cover .stat markup, picked by event composition per the cover register
    lock. composition is one of all-arrivals / all-restocks / mixed (derived over
    the full window population by content_queries.select_f7_arrivals)."""
    return f'<span class="num">{count}</span> {_F7_COVER_COPY[composition]}'


def f9_cover_stat_html(coral: str, vendor_count: int) -> str:
    """F9 cover .stat markup — "carried at," not a bare "at": vendor_count is
    the in-stock carrier count INCLUDING price-on-request carriers (a carry
    fact), but the reel renders only the priced cards, so a bare "at {N}
    vendors" reads as "buyable at {N} vendors" — false for the price-on-request
    carriers. "Carried" is a stock claim, not a buy claim. The dash is a
    near-black PROSE dash (it sits in .stat, not a .row .sep forest separator),
    per the cover register lock (branding-guide.md §"IG data-post copy" F7/F9
    cover-stat bullet, 2026-06-17).

    The prose is split into three .seg{1,2,3} spans so the F9 cover reveal
    (reel-frame-f9-lineage-cover-reveal.html) can stage it as three plain fades
    (CTK-173 Q2). The wrappers are presentation-only — get_text strips them and
    yields the byte-identical locked string, so the static cover template renders
    them inert (all visible) and the "carried at N" lock is untouched."""
    return (
        f'<span class="seg seg1"><span class="name">{_esc(coral)}</span></span>'
        f'<span class="seg seg2"> — carried at <span class="num">{vendor_count} vendors</span></span>'
        f'<span class="seg seg3"> right now.</span>'
    )


def render_f7_arrivals(
    *, count: int, composition: str, items: list[dict], now: datetime,
    out_path: str | Path, work_dir: str | Path | None = None,
    fps: int = video.DATA_CARD_MOTION.fps,
) -> Path:
    """F7 arrivals/back-in-stock kinetic carousel (CTK-173): a count-up COVER
    ("{count}" climbs to the true full-window count, label composition-picked —
    "new arrivals / back in stock / drops this week.") + one plain-reveal INNER per
    item, concatenated into one reel. Each item: {name, vendor, event_phrase,
    fields}. composition (all-arrivals / all-restocks / mixed) comes from
    select_f7_arrivals, derived over the full window population.

    composition is REQUIRED (no default): the cover label is the honest-claim
    surface, and a missing composition silently mislabelling a restock/mixed cover
    as "new arrivals" is the exact lie the F7/F8/F9 honest-count split exists to
    prevent. The driver always passes the selector's real composition; an unknown
    composition raises a KeyError on the label lookup (loud, by design).

    Motion follows the data (Q2 lock): the cover's {count} is the count-hero, so it
    gets the locked count-up; the inners get the plain staged reveal (no strike —
    Q1)."""
    cover = build_count_up(count=count, label=_F7_COVER_COPY[composition], fps=fps)
    inners = [
        build_inner_reveal(
            lead_html=_lead_html(it["name"], it["vendor"], it["event_phrase"]),
            fields=it["fields"], now=now, fps=fps,
        )
        for it in items
    ]
    return render_kinetic_carousel(slides=[cover, *inners], fps=fps, out_path=out_path, work_dir=work_dir)


def render_f9_lineage(
    *, coral: str, vendor_count: int, items: list[dict], now: datetime,
    out_path: str | Path, work_dir: str | Path | None = None,
    fps: int = video.DATA_CARD_MOTION.fps,
) -> Path:
    """F9 lineage spotlight kinetic carousel (CTK-173): a plain-staged-reveal COVER
    ("{coral} — carried at {n} vendors right now.", the dash a near-black PROSE dash,
    not a forest field separator) + one plain-reveal INNER per carrying vendor,
    concatenated into one reel. Each item: {name, vendor, fields} (event is
    'listed'). Cover copy + the "carried at N" lock per the register (see
    f9_cover_stat_html).

    Motion follows the data (Q2 lock): the F9 hero is the carry-spread, not a count,
    so the cover gets a plain staged reveal — count-up is reserved for the
    count-hero F7 cover."""
    cover = build_f9_cover_reveal(coral=coral, vendor_count=vendor_count, fps=fps)
    inners = [
        build_inner_reveal(
            lead_html=_lead_html(it["name"], it["vendor"], "listed"),
            fields=it["fields"], now=now, fps=fps,
        )
        for it in items
    ]
    return render_kinetic_carousel(slides=[cover, *inners], fps=fps, out_path=out_path, work_dir=work_dir)


# Count-up kinetic card timing (CTK-164 PB-2 sample) — branding-guide §"IG
# data-card motion" (2026-06-18). Structure locked (wordmark static, only digits
# move, near-black, build+hold cycle, IG loops). Curve LOCKED 2026-06-18 as a pure
# ease-out QUAD (Jon: "yes perfect. lock it and don't unlock it") — ONE curve, no
# branch, no compare variant. Do NOT reopen, re-render, revert to ease-out cubic
# (rejected as unreadable), or add compare variants without an explicit loud reopen
# flag from Jon first (lane process note 2026-06-18).
#
# The lock: a pure ease-out QUAD over the FULL build — the curve frozen in the
# 5:41pm count-up-sample-loop4.mp4 Jon picked for its deceleration (0 -> 237 -> 426 ->
# 568 -> 663 -> 710 -> 716 at 0.4s steps; +237/+189/+142/+95/+47/+6 — continuously
# decelerating the whole climb, gentle landing). Quad eases from frame 1, so the
# slowing is felt throughout (the rejected linear-tail experiment held a flat climb
# until a late knee and read as uniform — that path is gone, not branched). build
# 2.2s, hold 1.5s. The curve lives in count_up_values (pure + unit-asserted), not
# the template.
COUNT_UP_BUILD_SEC = 2.2
COUNT_UP_HOLD_SEC = 1.5


def _frame_count(seconds: float, fps: int) -> int:
    """Frames for a duration at fps, floored at 1 (mirrors MotionSpec.total_frames)."""
    return max(1, round(seconds * fps))


def count_up_values(
    count: int,
    *,
    fps: int = video.DATA_CARD_MOTION.fps,
    build_sec: float = COUNT_UP_BUILD_SEC,
    hold_sec: float = COUNT_UP_HOLD_SEC,
) -> list[int]:
    """The pure per-frame integer sequence the count-up card plays back: an ease-out
    QUAD over the FULL build (frac = 1 - (1 - p)^2, p = frame/build) — continuously
    decelerating from the first frame so the slowing is felt the whole climb and lands
    gently on count (the 5:41pm loop4 curve Jon picked). The last build frame is FORCED
    to exactly count (round, not floor), then a motionless hold at count.

    Guarantees (unit-asserted): values[0] == 0, values[-1] == count, monotonic
    non-decreasing, per-frame increments non-increasing (continuous deceleration),
    len == build + hold frames. Seek-driven and pure — the template indexes this array
    by frame, so the curve is tuned + tested here, never in JS."""
    n = int(count)
    build = _frame_count(build_sec, fps)
    hold = _frame_count(hold_sec, fps)

    out: list[int] = []
    for i in range(build):
        if i >= build - 1:
            frac = 1.0                                   # force terminal climb frame = exactly N
        else:
            p = i / build
            frac = 1 - (1 - p) ** 2                       # ease-out quad over the full build
        out.append(round(frac * n))
    out.extend([n] * hold)                               # motionless hold at N
    return out


def build_count_up(
    *,
    count: int,
    label: str = "new arrivals this week.",
    fps: int = video.DATA_CARD_MOTION.fps,
) -> tuple[str, int]:
    """Assemble the count-up card HTML + its total frame count. The per-frame value
    sequence is count_up_values (pure + unit-asserted; the locked ease-out quad),
    injected as a frame-indexed array the template plays back by seek. Returned
    separately from the render (mirrors build_f8_reveal) so the kinetic carousel
    orchestrator can rasterize the cover the same way it rasterizes the inners and
    concat them into one reel."""
    values = count_up_values(count, fps=fps)
    card_html = _fill(
        "reel-frame-count-up.html",
        LABEL=_esc(label),
        VALUES=json.dumps(values),
    )
    return card_html, len(values)


def render_count_up(
    *,
    count: int,
    label: str = "new arrivals this week.",
    fps: int = video.DATA_CARD_MOTION.fps,
    out_path: str | Path,
    work_dir: str | Path | None = None,
) -> Path:
    """The kinetic count-up card (single mp4): the headline number climbs 0 -> count
    on a pure ease-out quad (continuously decelerating, gentle landing — count_up_values),
    then holds ~1.5s, looping. The `coralticker.` wordmark + forest dot are static
    from frame 0 (the brand anchor never animates); the label is static; only the
    digits move, bold near-black — branding-guide §"IG data-card motion".

    This is a CONTENT animation, not a camera move: the per-frame value sequence is
    authored in count_up_values (pure, unit-asserted) and injected as a frame-indexed
    array, captured as a PNG sequence by rasterize_sequence and encoded by
    render_sequence (the image2 path). No MotionSpec, no DATA_CARD_MOTION camera zoom
    (canon L198). Returns out_path; per-frame PNGs land in work_dir/<stem>-frames for
    the 11pm debug.

    INV-01 does NOT bind: the count-up card renders no em-dash listing row (it is the
    aggregate warming card, free copy outside INV-01)."""
    out_path = Path(out_path)
    work_dir = Path(work_dir) if work_dir else out_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    card_html, total = build_count_up(count=count, label=label, fps=fps)
    frames = rasterize.rasterize_sequence(card_html, total, work_dir / f"{out_path.stem}-frames")
    video.render_sequence(frames, out_path, fps=fps)
    return out_path


# Reveal + strike-draw F8 drill-in timing (CTK-164 reveal sample-gate) — PROVISIONAL
# targets per branding-guide §"IG data-card motion" L196 (reveal) + L197 (strike-draw)
# + L199 (drill-in card ~5s). Each entry is (beat, seconds); `gap*`/`settle` are
# motionless pauses between reveals (no key in the schedule). Laid out sequentially
# by _reveal_schedule. The reveal/strike gate is marked UNFIRED in canon — these
# carry Jon's eyeball; flag for /brand-manager to record the locked values.
REVEAL_TIMELINE_SEC = [
    ("headline", 0.6),    # headline reveals (plain fade — the % is a settled fact)
    ("gap", 0.4),
    ("price_in", 0.4),    # "Price." label + old price fade in (reading-order first)
    ("old_hold", 0.85),   # un-struck LIVE-price beat (v3: 0.45 -> 0.85). The old price
                          #   sits un-struck + still long enough that slower readers land
                          #   on the live price BEFORE the strike fires, so the strike has
                          #   an un-struck beat to contrast against (else it reads as
                          #   "already struck"). The loop covers the slowest readers.
    ("strike", 0.55),     # SLOWED 0.4 -> 0.55: the line visibly travels L->R
    ("new_price", 0.4),   # new price (bold forest) reveals after the strike
    ("gap2", 0.2),
    ("sep", 0.3),         # forest em-dash draws width 0->100% from the left
    ("listed", 0.4),      # "Listed." label + value reveal
    ("settle", 0.3),
]
REVEAL_HOLD_SEC = 1.5     # motionless reading beat before the loop (total ~5.5s)

# Beat name -> the JS schedule key seekTo reads (only the animated beats; the
# gap/settle pauses advance the clock without an entry).
_REVEAL_BEAT_KEYS = {
    "headline": "hl", "price_in": "price", "strike": "strike",
    "new_price": "newp", "sep": "sep", "listed": "listed",
}


def _reveal_schedule(fps: int) -> tuple[dict, int]:
    """Lay REVEAL_TIMELINE_SEC out into frame windows for the seekTo schedule, plus
    the total frame count (build + hold). Each animated beat becomes a [start, end]
    frame window keyed per _REVEAL_BEAT_KEYS; gaps/holds/settle advance the clock only."""
    schedule: dict = {}
    cursor = 0
    for name, seconds in REVEAL_TIMELINE_SEC:
        frames = _frame_count(seconds, fps)
        if name in _REVEAL_BEAT_KEYS:
            schedule[_REVEAL_BEAT_KEYS[name]] = [cursor, cursor + frames]
        cursor += frames
    total = cursor + _frame_count(REVEAL_HOLD_SEC, fps)
    return schedule, total


def build_f8_reveal(
    *,
    name: str,
    pct: int,
    fields: list[dict],
    now: datetime,
    fps: int = video.DATA_CARD_MOTION.fps,
) -> tuple[str, int]:
    """Assemble the F8 reveal/strike-draw card HTML + its total frame count. The
    .row is the UNCHANGED format_data_row_html output (the same call render_f8_card_html
    makes), so the held end-frame's row text == data_row.format_data_row byte-for-byte
    by construction — the animation only reveals it, never re-formats it. Returned
    separately from the render so the parity test can drive seekTo(total-1) in a
    browser and assert the held-frame row text directly."""
    schedule, total = _reveal_schedule(fps)
    card_html = _fill(
        "reel-frame-f8-reveal.html",
        STAT_NAME=_esc(name),
        STAT_PCT=str(int(pct)),
        DATA_ROW=format_data_row_html(fields, now),
        SCHEDULE=json.dumps(schedule),
    )
    return card_html, total


def render_f8_reveal(
    *,
    name: str,
    pct: int,
    fields: list[dict],
    now: datetime,
    out_path: str | Path,
    fps: int = video.DATA_CARD_MOTION.fps,
    work_dir: str | Path | None = None,
) -> Path:
    """F8 superlative drill-in with the reveal + strike-draw motion (CTK-164 reveal
    sample): headline PLAIN-reveals (the % is a settled fact — the count-up variant
    was dropped, Jon 2026-06-18), then the em-dash row builds in reading order — the
    Price field reveals via the strike-draw (old near-black -> un-struck hold ->
    struck -> new bold-forest), the forest em-dash draws L->R, the Listed field
    reveals — then a ~1.5s hold, looping. Forest only on the em-dash + the new price
    (no budget expansion); ease-out only. Built on the locked count-up engine
    (rasterize_sequence + render_sequence); content animation is the PNG sequence,
    never an ffmpeg filter (INV-06 PB-2).

    INV-01 binds here (unlike the count-up): the held end-frame's row IS
    format_data_row_html output, parity-pinned to data_row.format_data_row. Returns
    out_path; per-frame PNGs land in work_dir/<stem>-frames for the 11pm debug."""
    out_path = Path(out_path)
    work_dir = Path(work_dir) if work_dir else out_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    card_html, total = build_f8_reveal(name=name, pct=pct, fields=fields, now=now, fps=fps)
    frames = rasterize.rasterize_sequence(card_html, total, work_dir / f"{out_path.stem}-frames")
    video.render_sequence(frames, out_path, fps=fps)
    return out_path


def render_f8_superlative(
    *,
    name: str,
    pct: int,
    fields: list[dict],
    now: datetime,
    out_path: str | Path,
    work_dir: str | Path | None = None,
) -> Path:
    """F8 end-to-end (single card, no concat): assemble card HTML -> rasterize to
    PNG -> render_kenburns with DATA_CARD_MOTION -> looping vertical MP4 at
    out_path. Returns out_path.

    The PNG lands beside out_path (or in work_dir) so the intermediate frame is
    inspectable for the 11pm debug."""
    out_path = Path(out_path)
    work_dir = Path(work_dir) if work_dir else out_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    png_path = work_dir / (out_path.stem + ".png")

    card_html = render_f8_card_html(name=name, pct=pct, fields=fields, now=now)
    rasterize.rasterize_html(card_html, png_path)
    video.render_kenburns(png_path, out_path, motion_spec=video.DATA_CARD_MOTION)
    return out_path


# ---------------------------------------------------------------------------
# CTK-173 — F7/F9 kinetic carousel: a count-up / plain-reveal COVER + plain-reveal
# INNERS, concatenated into one reel. The inner reveal is the CTK-172 F8 reveal
# timeline MINUS the strike beat (Q1 lock 2026-06-19: F7/F9 heroes are the arrival
# event / carry-spread, not a price move — no strike-draw). Every beat duration
# below is lifted VERBATIM from the locked REVEAL_TIMELINE_SEC palette (no new timing
# minted): the 0.6 headline beat, the 0.4 reveal beats, the 0.4 gap, the 0.2 gap2,
# the 0.3 settle, the 1.5 hold. ease-out cubic, opacity/clip only (canon L196/L198).
# ---------------------------------------------------------------------------

# F7/F9 inner plain-reveal: lead -> Price -> forest em-dash draw L->R -> Listed.
INNER_REVEAL_TIMELINE_SEC = [
    ("lead", 0.6),     # the arrival/listed lead line plain-reveals (the hero)
    ("gap", 0.4),
    ("price", 0.4),    # "Price." label + value reveal
    ("gap2", 0.2),
    ("sep", 0.3),      # the forest em-dash draws L->R
    ("listed", 0.4),   # "Listed." label + value reveal
    ("settle", 0.3),
]
INNER_REVEAL_HOLD_SEC = 1.5

# F9 cover plain-staged-reveal: name -> "carried at N vendors" -> "right now."
COVER_REVEAL_TIMELINE_SEC = [
    ("seg1", 0.6),
    ("gap", 0.4),
    ("seg2", 0.4),
    ("gap2", 0.2),
    ("seg3", 0.4),
    ("settle", 0.3),
]
COVER_REVEAL_HOLD_SEC = 1.5


def _lay_reveal(timeline_sec: list[tuple[str, float]], hold_sec: float, fps: int) -> tuple[dict, int]:
    """Lay a [(beat, seconds), ...] reveal timeline into {beat: [start, end]} frame
    windows + the total frame count (build + a motionless hold). Beats named 'gap*'
    or 'settle' are motionless pauses — they advance the clock without a window (no
    JS reveal target). Generic mirror of _reveal_schedule (the F8 path); the F8
    schedule stays its own function so the locked F8 timeline is never touched."""
    # keep cursor math in sync with _reveal_schedule (intentional dup — the split
    # protects the locked F8 timeline; a future off-by-one fix must touch BOTH).
    schedule: dict = {}
    cursor = 0
    for name, seconds in timeline_sec:
        frames = _frame_count(seconds, fps)
        if not (name.startswith("gap") or name == "settle"):
            schedule[name] = [cursor, cursor + frames]
        cursor += frames
    total = cursor + _frame_count(hold_sec, fps)
    return schedule, total


def build_inner_reveal(
    *,
    lead_html: str,
    fields: list[dict],
    now: datetime,
    template_name: str = "reel-frame-inner-reveal.html",
    fps: int = video.DATA_CARD_MOTION.fps,
) -> tuple[str, int]:
    """Assemble an F7/F9 inner plain-reveal card HTML + its total frame count. The
    .row is the UNCHANGED format_data_row_html output (the same adapter the static
    inner injects), so the held end-frame's row text == data_row.format_data_row
    byte-for-byte by construction — the animation only reveals it, never re-formats
    it (INV-01). Returned separately from the render so the parity test can drive
    seekTo(total-1) in a browser and assert the held-frame row text directly."""
    schedule, total = _lay_reveal(INNER_REVEAL_TIMELINE_SEC, INNER_REVEAL_HOLD_SEC, fps)
    card_html = _fill(
        template_name,
        LEAD_HTML=lead_html,
        DATA_ROW=format_data_row_html(fields, now),
        SCHEDULE=json.dumps(schedule),
    )
    return card_html, total


def build_f9_cover_reveal(
    *,
    coral: str,
    vendor_count: int,
    fps: int = video.DATA_CARD_MOTION.fps,
) -> tuple[str, int]:
    """Assemble the F9 cover plain-staged-reveal HTML + its total frame count. The
    .stat is the UNCHANGED f9_cover_stat_html output (the locked 'carried at N'
    prose in presentation-only .seg spans), so the held end-frame strips to the
    byte-identical locked cover string — the stage is opacity-only, never a copy
    change."""
    schedule, total = _lay_reveal(COVER_REVEAL_TIMELINE_SEC, COVER_REVEAL_HOLD_SEC, fps)
    card_html = _fill(
        "reel-frame-f9-lineage-cover-reveal.html",
        STAT_HTML=f9_cover_stat_html(coral, vendor_count),
        SCHEDULE=json.dumps(schedule),
    )
    return card_html, total


def render_kinetic_carousel(
    *,
    slides: list[tuple[str, int]],
    fps: int = video.DATA_CARD_MOTION.fps,
    out_path: str | Path,
    work_dir: str | Path | None = None,
) -> Path:
    """Render an ordered list of (card_html, total_frames) slides — cover FIRST, then
    inners in order — into one reel. Each slide is captured as a seek-driven PNG
    sequence (rasterize_sequence) and encoded via render_sequence; every clip routes
    through render_sequence's shared _encode_args, so concat_clips stream-copies them
    into one reel with no re-encode (INV-06 PB-6: the count-up / plain-reveal cover
    and the plain-reveal inners satisfy the demuxer precondition by construction —
    same profile/level/gop/dims/fps). Imports the shared video.py primitives, never
    forks. Returns out_path; per-slide PNG sequences + clips land in work_dir for the
    11pm debug."""
    out_path = Path(out_path)
    work_dir = Path(work_dir) if work_dir else out_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    for idx, (card_html, total) in enumerate(slides):
        label = "cover" if idx == 0 else f"inner{idx - 1}"
        frames = rasterize.rasterize_sequence(card_html, total, work_dir / f"{out_path.stem}-{label}-frames")
        clip = work_dir / f"{out_path.stem}-{label}.mp4"
        video.render_sequence(frames, clip, fps=fps)
        clips.append(clip)
    video.concat_clips(clips, out_path)
    return out_path
