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
        # Struck old value + emphasized new value; the literal space between the
        # spans reproduces _format_value's "old new" text.
        return (
            f'<span class="struck">{_esc(value["oldValue"])}</span> '
            f'<span class="new">{_esc(value["newValue"])}</span>'
        )
    if kind == "invalidated":
        # Strike styling is right for the card (visual channel); text is the bare
        # value, matching the mirror's non-DOM "carry the bare value".
        return f'<span class="struck">{_esc(value["value"])}</span>'
    if kind == "italic":
        return f'<span class="val"><em>{_esc(value["value"])}</em></span>'
    raise ValueError(f"format_data_row_html: unhandled value kind {kind!r}")


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


def render_f8_card_html(*, name: str, pct: int, fields: list[dict], now: datetime) -> str:
    """Assemble the F8 superlative card HTML: inject the coral name + drop percent
    into the stat line and the INV-01 data row into the .row. Returns a full HTML
    document ready for rasterize."""
    template = (_TEMPLATE_DIR / "reel-frame-f8-superlative.html").read_text(encoding="utf-8")
    return (
        template
        .replace("{{STAT_NAME}}", _esc(name))
        .replace("{{STAT_PCT}}", str(pct))
        .replace("{{DATA_ROW}}", format_data_row_html(fields, now))
    )


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
