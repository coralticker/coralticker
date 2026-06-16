"""CTK-159 Slice B — Instagram spotlight publish-or-notify adapter.

Turns a scored ig_select candidate into a postable artifact and notifies Jon to
publish (D-1: semi-automated, human-in-the-loop). Mirrors the pure-core + I/O-
shell shape of ig_select.py / leak_scan.py: caption rendering is pure and unit-
driven; selection and the Slack POST are the I/O shell.

What the pipeline emits (the D-1 output contract, against CTK-157 rev4 — the
caption template of record):

  Line 0  optional personal line   — OMITTED. Never auto-generated; Jon adds a
                                      genuine aside only when he has one (rev4
                                      §"Optional personal line"). A forced-on-
                                      every-post opener is anti-canon.
  Line 1  {coral name} — {detail}  — the searchable lineage/species NAME a
                                      collector types when hunting (rev4 L39 +
                                      plan §Caption-system L107) is pre-filled
                                      from the named_corals match; absent a
                                      match the name slot is a {coral name}
                                      placeholder (the data plane has no clean
                                      lineage name without a match — raw vendor
                                      titles are not searchable names). The
                                      em-dash physical-detail half is LEFT BLANK
                                      for Jon — a human eyes-on-the-photo
                                      observation that D-1 forbids auto-
                                      generating; rendered as a fill-prompt, not
                                      content.
  Line 2  {Verb} at {SH} (@handle) — FULLY rendered. The lead-event arm maps to
                                      the canon verb (just-listed -> Listed,
                                      back-in-stock -> Back in stock,
                                      price-dropped -> Price dropped); vendor
                                      shorthand + parenthetical @handle come from
                                      branding-guide.md §Usage-rules IG-handle
                                      table (mirrored in VENDOR_IG below).
  Line 3  fixed closer             — "Full feed at coralticker.com — link in
                                      bio." Verbatim (rev4 L53).

  First comment  8-12 tag block    — per rev4 §"The hashtag layer". A lineage-
                                      name tag candidate (from the coral slug)
                                      carries a [verify live tag-feed] marker;
                                      the vendor branded tag renders ONLY for a
                                      vendor that has one (VENDOR_IG branded
                                      column — #battlecorals alone today) and
                                      carries a [verify vendor branded tag]
                                      marker. The ~5-7 niche reef-category tags
                                      depend on the coral TYPE, which is not in
                                      the data plane, so the block emits a
                                      {niche reef-category tags} fill-prompt
                                      rather than guess a wrong category. The
                                      [verify ...] markers are the standing
                                      per-post checks rev4 L74/L150 define.

Notify path (D-2 fallback = v1, per Slice-B B-6): render the artifact to the
CTK-011 Slack operator channel; Jon eyeballs the crop (image URL unfurls a
preview — brand-safety per D-1), fills Line 0 / the Line-1 detail, and taps to
post. A programmatic scheduler draft-push (Metricool/Later) is the Phase-2
graduation — when it lands only the final POST target swaps; selection, caption,
and cadence are unchanged. NO unofficial auto-login bots (account-ban risk).

D-5: the image is the STATIC mirrored vendor photo already in the pipeline. No
motion in v1 (Ken Burns deferred to CTK-163's owned-asset data-viz; AI animation
is rejected canon per branding-guide L129).

Run via:
  python -m scrapers.tools.ig_spotlight [--mode daily|weekly-roundup]
                                        [--top-n N] [--dry-run]

--dry-run renders to stdout without posting (the workflow_dispatch dry_run input
+ the path T7b acceptance drives). Reads NEON_DATABASE_URL + SLACK_WEBHOOK_URL
from the environment (.env via scrapers.common.db). Exit 0 on a clean run; 1 on
error (loud-failure posture).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scrapers.tools.ig_select import Candidate, DEFAULT_TOP_N
from scrapers.tools.content_queries import CONTENT_FORMATS, FormatDescriptor

# A-path reel output dir (CTK-164). Overridable via --out-dir; the GH Actions
# render uploads this dir as the run artifact (post_slack is a text webhook and
# cannot carry the file — Slack gets the pointer, the MP4 rides the artifact).
DEFAULT_REEL_DIR = "build/reels"

# ---------------------------------------------------------------------------
# Brand canon, mirrored from branding-guide.md §Usage-rules IG-handle table
# (CTK-157, Jon-confirmed 2026-06-14). Keyed by DB vendor_slug. CTK-159 renders
# the @mention + branded hashtag from THIS table; canon is the source of truth.
# A vendor missing from this table raises in vendor_attribution() rather than
# emit a handle-less caption — a dropped @mention silently kills the reshare,
# which is the one thing the caption exists to do (rev4 L50). ReefnBid is absent
# by design (no shop account, no active scraper — out of the spotlight rotation).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VendorIG:
    shorthand: str
    handle: str
    branded_hashtag: str | None


VENDOR_IG: dict[str, VendorIG] = {
    "wwc":             VendorIG("WWC",            "@worldwidecorals",             None),
    "jf":              VendorIG("JF",             "@jason_fox_signature_corals",  None),
    "tsa":             VendorIG("TSA",            "@topshelfaquatics",            None),
    "battlecorals":    VendorIG("Battlecorals",   "@battlecorals",                "#battlecorals"),
    "unique_corals":   VendorIG("Unique Corals",  "@uniquecorals",                None),
    "aquasd":          VendorIG("Aqua SD",        "@aqua_sd",                     None),
    "pacific_east":    VendorIG("PEA",            "@pacificeastaquaculture",      None),
    "tidal_gardens":   VendorIG("Tidal Gardens",  "@tidalgardens",                None),
    "vivid_aquariums": VendorIG("Vivid",          "@vivid_aquariums",             None),
    "poto":            VendorIG("POTO",           "@piecesoftheocean",            None),
    "reef_chasers":    VendorIG("Reef Chasers",   "@reefchasers",                 None),
}

# Lead-event arm -> canon event verb (rev4 L45-48; cross-channel verb canon).
# price-dropped covers both a CT-observed drop and a vendor markdown (rev4 L45).
EVENT_VERB: dict[str, str] = {
    "just-listed": "Listed",
    "back-in-stock": "Back in stock",
    "price-dropped": "Price dropped",
}

# Line-1 name slot when there is no named_corals match: a fill-prompt, NOT a
# guess. Raw vendor titles aren't searchable lineage names (rev4 L39).
NAME_PLACEHOLDER = "{coral name}"

# Line-1 em-dash detail: the human photo-observation D-1 forbids auto-generating.
# Rendered as a fill-prompt so the blank slot is unambiguous in the operator
# channel; this is NOT generated description.
DETAIL_PROMPT = "[one thing you can see in the photo]"

# First-comment niche tags depend on coral TYPE (not in the data plane) — a
# fill-prompt, not a guess at the category (rev4 L68 ~5-7 niche reef tags).
NICHE_PROMPT = "{niche reef-category tags}"

CLOSER = "Full feed at coralticker.com — link in bio."


# ---------------------------------------------------------------------------
# CTK-161 D-2 — content-format auto-publish gate.
#
# The publish gate lives HERE in the Slice-B adapter, NOT the query layer: the
# content query layer (content_queries.py) computes every format ungated; the
# adapter decides what auto-publishes. Only NON-comparative formats (aggregate
# activity, most-restocked, single-listing drop) enter the auto-publish path. A
# COMPARATIVE format (cheapest-across-vendors, market-report) — one whose render
# names which shop is cheapest — computes + renders to a draft but routes to
# manual hold: a public price-ranking waits for Jon's deliberate publish call
# (plan §Build-vs-publish split), because it commoditizes the vendor pricing the
# reshare strategy + future partnerships lean on.
#
# WIRING: the content-format render/publish loop is a future CTK-161 consumer
# slice (the data-post rendering on top of the shared layer). It MUST route its
# format descriptors through auto_publishable() before any auto-POST, so a
# comparative format can never auto-publish by omission. Pre-wired here, ahead of
# that loop, so the gate exists before the first content post can be drafted.
# ---------------------------------------------------------------------------


def auto_publishable(descriptor: FormatDescriptor) -> bool:
    """D-2 gate: True only for a NON-comparative format. The single code
    obligation of the build-vs-publish split — comparative formats never enter
    the auto-publish path."""
    return not descriptor.comparative


def auto_publishable_formats() -> list[FormatDescriptor]:
    """The content formats cleared for auto-publish (comparative == false). The
    comparative ones (cheapest-across-vendors, market-report) are computed +
    render-ready but excluded here — manual-hold until Jon's publish call."""
    return [d for d in CONTENT_FORMATS.values() if auto_publishable(d)]


# ---------------------------------------------------------------------------
# Pure core — no DB, no network. Tests drive these directly.
# ---------------------------------------------------------------------------


def vendor_attribution(vendor_slug: str) -> VendorIG:
    """The vendor's IG attribution (shorthand / @handle / branded hashtag).
    Raises KeyError loudly on an unmapped slug — a missing @mention silently
    kills the reshare, so a map-miss must fail the run, not emit a broken
    caption (loud-failure posture)."""
    try:
        return VENDOR_IG[vendor_slug]
    except KeyError:
        raise KeyError(
            f"vendor_slug {vendor_slug!r} not in VENDOR_IG (branding-guide.md "
            f"§Usage-rules IG-handle table). Add the handle before this vendor "
            f"can enter the spotlight rotation."
        ) from None


def event_verb(arm: str) -> str:
    """The canon event verb for a lead-event arm. Raises loudly on an unknown
    arm — get_listing_lead_event only emits the three mapped arms, so an unmapped
    value is a contract break, not a row to paper over."""
    try:
        return EVENT_VERB[arm]
    except KeyError:
        raise KeyError(
            f"lead-event arm {arm!r} has no canon verb (expected one of "
            f"{sorted(EVENT_VERB)})."
        ) from None


def lineage_hashtag(coral_slug: str | None) -> str | None:
    """A best-guess lineage-name hashtag candidate from the named_corals slug,
    or None when there is no match. Per rev4 L74 lineage tags are candidates,
    not confirmed — the [verify live tag-feed] marker (added by the caller) is
    the standing check Jon runs before posting. Returns just the bare #tag."""
    if not coral_slug:
        return None
    token = "".join(ch for ch in coral_slug.lower() if ch.isalnum())
    return f"#{token}" if token else None


def render_caption(c: Candidate) -> str:
    """The three-line caption skeleton (Line 0 omitted; Line 1 name-filled,
    detail-blank; Line 2 fully rendered; Line 3 verbatim closer). The poster
    fills the Line-1 detail and may prepend an optional Line 0."""
    name = c.coral_name if c.named_coral_id is not None and c.coral_name else NAME_PLACEHOLDER
    v = vendor_attribution(c.vendor_slug)
    line1 = f"{name} — {DETAIL_PROMPT}"
    line2 = f"{event_verb(c.arm)} at {v.shorthand} ({v.handle})."
    return "\n".join([line1, line2, CLOSER])


def render_first_comment(c: Candidate) -> str:
    """The first-comment hashtag block (rev4 §"The hashtag layer"): a niche-tag
    fill-prompt, a lineage-tag candidate carrying [verify live tag-feed] when a
    named match exists, and the vendor branded tag carrying [verify vendor
    branded tag] only for a vendor that has one. 8-12 tags total once Jon fills
    the niche slot."""
    parts = [NICHE_PROMPT]
    lineage = lineage_hashtag(c.coral_slug)
    if lineage:
        parts.append(f"{lineage}[verify live tag-feed]")
    branded = vendor_attribution(c.vendor_slug).branded_hashtag
    if branded:
        parts.append(f"{branded}[verify vendor branded tag]")
    return " ".join(parts)


def render_operator_block(c: Candidate) -> str:
    """The Slack operator-channel render for one candidate (the "help me send"
    surface): the image URL (Slack unfurls a preview so Jon eyeballs the crop),
    the copy-paste caption skeleton, the first-comment block, the listing URL,
    and the score breakdown. Code-fenced blocks copy cleanly on tap."""
    coral = c.coral_name or c.raw_title or f"id={c.listing_id}"
    sh = vendor_attribution(c.vendor_slug).shorthand
    xv = " · cross-vendor-cheapest" if c.is_cross_vendor_cheapest else ""
    return (
        f"*{sh} — {coral}*  (score {c.score:.1f}{xv})\n"
        f"image (eyeball the crop): {c.image_url}\n"
        f"listing: {c.product_url}\n"
        f"caption skeleton — add an optional Line 0, fill the Line-1 photo detail:\n"
        f"```\n{render_caption(c)}\n```\n"
        f"first comment — fill the niche tags, verify the marked tags:\n"
        f"```\n{render_first_comment(c)}\n```"
    )


def render_notification(mode: str, candidate_count: int, gated_count: int,
                        selected: list[Candidate]) -> str:
    """The full operator-channel message: a header summary + one block per
    selected candidate. daily -> one block; weekly-roundup -> the top-N set."""
    header = (
        f"ig-spotlight {mode} — {len(selected)} candidate(s) to post "
        f"({candidate_count} scanned, {gated_count} passed the image gate)"
    )
    if not selected:
        return header + "\n(nothing cleared the image gate this window.)"
    blocks = "\n\n".join(render_operator_block(c) for c in selected)
    return f"{header}\n\n{blocks}"


# ---------------------------------------------------------------------------
# I/O shell — selection (via ig_select) + Slack POST.
# ---------------------------------------------------------------------------


def run(mode: str, top_n: int, dry_run: bool = False) -> int:
    from scrapers.common import db
    from scrapers.tools import ig_select

    conn = db.get_conn()
    try:
        candidates, gated, selected = ig_select.select(conn, mode, top_n)
    finally:
        conn.close()

    message = render_notification(mode, len(candidates), len(gated), selected)

    if dry_run:
        print(message)
        return 0

    from scrapers.common.cohort_signal import post_slack
    post_slack(message)
    print(f"ig-spotlight {mode}: posted {len(selected)} candidate(s) to the operator channel.")
    return 0


# ---------------------------------------------------------------------------
# CTK-164 A-path — Ken Burns reel render + delivery.
#
# Surface is LOCKED A-path only: pan/zoom the CLEAN mirrored vendor photo. No
# card, no baked data row, no CoralTicker branding on the image (CTK-157 §5
# reshare canon; attribution rides the caption per CTK-159 D-4). INV-01 does
# NOT apply — no listing line renders on the image, so data_row.py is untouched.
# ---------------------------------------------------------------------------


def render_reel(c: Candidate, out_dir: str | Path) -> Path:
    """Render one candidate's clean mirrored photo to a Ken Burns MP4. Fetches
    the 600px mirror, composes the 9:16 blurred-fill frame, encodes the pan.
    Raises on fetch or render failure (the batch driver catches + skips)."""
    from scrapers.common import video
    from scrapers.common.http import fetch_image

    if not c.image_url:
        raise RuntimeError(f"candidate id={c.listing_id} has no image_url (image gate should have dropped it)")
    image_bytes = fetch_image(c.image_url)
    if image_bytes is None:
        raise RuntimeError(f"fetch_image returned None for {c.image_url}")

    frame = video.compose_9x16_blurred_fill(image_bytes)
    out_path = Path(out_dir) / f"{c.vendor_slug}-{c.listing_id}.mp4"

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        frame.save(tmp, "PNG")
        tmp.close()
        video.render_kenburns(tmp.name, out_path, motion_spec=video.DEFAULT_MOTION)
    finally:
        os.unlink(tmp.name)
    return out_path


def render_batch(conn, mode: str, top_n: int, out_dir: str | Path):
    """Select candidates and render each selected one to a reel. A single
    render failure skips that candidate (logged) rather than crashing the batch
    — the grid-stocking pass should bank the reels that do render. Returns
    (all_candidates, gated, results) where results is [(Candidate, Path|None)]."""
    from scrapers.tools import ig_select

    candidates, gated, selected = ig_select.select(conn, mode, top_n)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    results: list[tuple[Candidate, Path | None]] = []
    for c in selected:
        try:
            path: Path | None = render_reel(c, out_dir)
        except Exception as e:  # noqa: BLE001 — skip one, keep the batch going
            print(
                f"WARN: reel render failed for {c.vendor_slug} id={c.listing_id}: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
            path = None
        results.append((c, path))
    return candidates, gated, results


def render_reel_block(c: Candidate, path: Path | None) -> str:
    """The operator block for one rendered reel: the existing caption/eyeball
    block plus a pointer to the MP4 on disk (Slack carries text only)."""
    pointer = (
        f"reel rendered -> {path}"
        if path is not None
        else "reel render FAILED (see logs) — post the static image instead"
    )
    return f"{render_operator_block(c)}\n{pointer}"


def render_reel_notification(mode: str, candidate_count: int, gated_count: int,
                             results: list[tuple[Candidate, Path | None]],
                             out_dir: str | Path) -> str:
    """The operator-channel message for a reel batch: a header summary + one
    block per candidate, each pointing at its MP4. The MP4s ride the run
    artifact / out-dir — post_slack is a webhook and cannot upload files."""
    rendered = sum(1 for _, p in results if p is not None)
    header = (
        f"ig-spotlight {mode} reels — {rendered}/{len(results)} rendered "
        f"({candidate_count} scanned, {gated_count} passed the image gate). "
        f"Grab the MP4s from {out_dir} (run artifact)."
    )
    if not results:
        return header + "\n(nothing cleared the image gate this window.)"
    blocks = "\n\n".join(render_reel_block(c, p) for c, p in results)
    return f"{header}\n\n{blocks}"


def run_reels(mode: str, top_n: int, out_dir: str | Path, dry_run: bool = False) -> int:
    from scrapers.common import db

    conn = db.get_conn()
    try:
        candidates, gated, results = render_batch(conn, mode, top_n, out_dir)
    finally:
        conn.close()

    message = render_reel_notification(mode, len(candidates), len(gated), results, out_dir)

    if dry_run:
        print(message)
        return 0

    from scrapers.common.cohort_signal import post_slack
    post_slack(message)
    rendered = sum(1 for _, p in results if p is not None)
    print(f"ig-spotlight {mode} reels: {rendered} rendered to {out_dir}; notified operator channel.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("daily", "weekly-roundup"), default="daily",
                        help="Selection window + size (daily top-1 / weekly-roundup top-N).")
    parser.add_argument("--top-n", type=int, default=None,
                        help="Override the per-mode default selection size.")
    parser.add_argument("--reels", action="store_true",
                        help="Render Ken Burns reels (CTK-164 A-path) instead of the static-image block.")
    parser.add_argument("--out-dir", default=DEFAULT_REEL_DIR,
                        help="Reel output dir (--reels mode; uploaded as the GH Actions artifact).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render to stdout without posting to the operator channel.")
    args = parser.parse_args()
    top_n = args.top_n if args.top_n is not None else DEFAULT_TOP_N[args.mode]
    try:
        if args.reels:
            return run_reels(args.mode, top_n, args.out_dir, dry_run=args.dry_run)
        return run(args.mode, top_n, dry_run=args.dry_run)
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1 (loud-failure posture)
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
