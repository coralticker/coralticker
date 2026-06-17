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
    .stat inner markup (the caller owns the brand copy + inline spans)."""
    return _fill(template_name, STAT_HTML=stat_html)


def render_inner_html(template_name: str, lead_html: str, fields: list[dict], now: datetime) -> str:
    """A carousel INNER frame (lead + INV-01 data row). lead_html is prebuilt
    (_lead_html); the row is the field-driven adapter output."""
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
    out_path; intermediate PNGs/clips land in work_dir for the 11pm debug."""
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
    """F9 cover .stat markup — the dash is a near-black PROSE dash (it sits in
    .stat, not a .row .sep forest separator), per the cover register lock
    (branding-guide.md §"IG data-post copy" + CTK-161 rev2 L225/L230)."""
    return (
        f'<span class="name">{_esc(coral)}</span> — at '
        f'<span class="num">{vendor_count} vendors</span> right now.'
    )


def render_f7_arrivals(
    *, count: int, composition: str, items: list[dict], now: datetime,
    out_path: str | Path, work_dir: str | Path | None = None,
) -> Path:
    """F7 arrivals/back-in-stock carousel: a stat-only cover (composition-picked
    per the cover register — "{count} new arrivals / back in stock / drops this
    week.") + one inner per item. Each item: {name, vendor, event_phrase, fields}.
    composition (all-arrivals / all-restocks / mixed) comes from select_f7_arrivals,
    derived over the full window population.

    composition is REQUIRED (no default): the cover stat is the honest-claim surface,
    and a missing composition silently mislabelling a restock/mixed cover as "new
    arrivals" is the exact lie the F7/F8/F9 honest-count split exists to prevent.
    The driver always passes the selector's real composition."""
    cover = render_cover_html("reel-frame-f7-arrivals-cover.html", f7_cover_stat_html(count, composition))
    inners = [
        render_inner_html(
            "reel-frame-f7-arrivals.html",
            _lead_html(it["name"], it["vendor"], it["event_phrase"]),
            it["fields"], now,
        )
        for it in items
    ]
    return render_carousel(cover_html=cover, inner_htmls=inners, now=now, out_path=out_path, work_dir=work_dir)


def render_f9_lineage(
    *, coral: str, vendor_count: int, items: list[dict], now: datetime,
    out_path: str | Path, work_dir: str | Path | None = None,
) -> Path:
    """F9 lineage spotlight carousel: a stat-only cover ("{coral} — at {n} vendors
    right now.", the dash a near-black PROSE dash, not a forest field separator) +
    one inner per carrying vendor. Each item: {name, vendor, fields} (event is
    'listed'). Cover copy per the register lock (see f9_cover_stat_html)."""
    cover = render_cover_html("reel-frame-f9-lineage-cover.html", f9_cover_stat_html(coral, vendor_count))
    inners = [
        render_inner_html(
            "reel-frame-f9-lineage.html",
            _lead_html(it["name"], it["vendor"], "listed"),
            it["fields"], now,
        )
        for it in items
    ]
    return render_carousel(cover_html=cover, inner_htmls=inners, now=now, out_path=out_path, work_dir=work_dir)


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
