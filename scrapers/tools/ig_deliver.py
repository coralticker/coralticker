"""CTK-176 — Telegram daily-reel delivery (laptop -> phone last-mile).

The IG content engine (CTK-159 selection -> CTK-161 content layer -> CTK-164/172/
173 render) banks a reel per day at build/reels/{vendor_slug}-{listing_id}.mp4
with a caption sidecar (.txt) emitted alongside it by ig_spotlight.render_batch
(CTK-176 cross-touch). Nothing carries that pair off the laptop. This script is
the last-mile: it posts each reel + its caption to a private Telegram chat so Jon
saves the video to his camera roll and copy-pastes the caption into IG by hand.

Design mirrors ig_spotlight.py / ig_select.py: a pure core (no DB, no network)
that the tests drive directly, plus an I/O shell that does the Telegram POSTs.

  Pure core:
    pair_reels(reel_dir)     -- glob top-level *.mp4, pair each with its .txt
    read_caption(txt_path)   -- the sidecar text, or None when absent
    plan_caption(caption)    -- caption-cap branch: (doc_caption, followup_message)

  I/O shell:
    send_document / send_message  -- direct requests.post, raise on non-2xx
    deliver_pair                  -- one reel: sendDocument [+ conditional sendMessage]
    run                           -- pair, deliver, move delivered pairs aside

Why a sidecar, not re-selection: re-running ig_select.select() at delivery time
is non-idempotent (re-fires record_picks, may pick a different candidate than the
one actually rendered). The rendered artifact is the source of truth; the sidecar
binds the caption to the exact .mp4 on disk.

Delivery is deliver-paired + move-to-delivered/: every *.mp4 that HAS its caption
sidecar (.txt) goes out, then the pair moves to build/reels/delivered/. That makes
a re-run idempotent (delivered pairs are out of the source glob) and an empty dir a
clean no-op (also covers a missing-reel day). build/reels/delivered/ is excluded
from the source glob (top-level only).

Pair-gate (CTK-176): a caption-less *.mp4 is SKIPPED, not shipped. render_batch
always emits the sidecar on a successful render, so a sidecar-less .mp4 is a stray
(a sample/experimental render -- build/reels/ is shared with the CTK-164/172/173
kinetic-card renders), not a daily reel. The gate keeps strays out of the chat
without a per-file allowlist.

sendDocument, NOT sendVideo: sendVideo recompresses the MP4 for inline playback,
degrading the quality Jon needs for IG. sendDocument ships the file byte-for-byte;
Telegram still renders an inline preview and Jon saves the original at full quality.

Caption-cap: Telegram's media-caption limit is 1024 chars; IG captions can exceed
it. <= 1024 attaches to sendDocument; > 1024 sends the document caption-less, then
the full caption as a follow-up sendMessage (4096 cap).

Run via:
  python -m scrapers.tools.ig_deliver [--reel-dir build/reels] [--dry-run]

--dry-run prints what would send without POSTing (and needs no token/chat id).
Reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from the environment (.env via
scrapers.common.db's load_dotenv). Exit 0 on a clean run (including the no-op
empty-dir day); 1 on error (loud-failure posture).
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REEL_DIR = "build/reels"
DELIVERED_SUBDIR = "delivered"

# Telegram media-caption cap (sendDocument). Inclusive: a caption of exactly this
# length still attaches; one char over splits to a follow-up sendMessage.
TELEGRAM_CAPTION_LIMIT = 1024

# Telegram message cap (sendMessage), for the over-length follow-up.
TELEGRAM_MESSAGE_LIMIT = 4096

API_BASE = "https://api.telegram.org/bot{token}/{method}"


# ---------------------------------------------------------------------------
# Pure core — no DB, no network. Tests drive these directly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReelPair:
    """One reel to deliver: the .mp4 and its caption sidecar (None when the .txt
    is absent — the reel still ships, caption-less)."""
    mp4: Path
    txt: Path | None


def pair_reels(reel_dir: str | Path) -> list[ReelPair]:
    """Pair every top-level *.mp4 in reel_dir with its same-stem .txt sidecar.
    Sorted by filename for stable ordering. Non-recursive, so the delivered/
    subdir (and any other subdir) is skipped — only reels awaiting delivery are
    returned. A missing reel dir yields an empty list (a no-render day is a clean
    no-op, not an error)."""
    base = Path(reel_dir)
    if not base.is_dir():
        return []
    pairs: list[ReelPair] = []
    for mp4 in sorted(base.glob("*.mp4")):
        txt = mp4.with_suffix(".txt")
        pairs.append(ReelPair(mp4=mp4, txt=txt if txt.is_file() else None))
    return pairs


def read_caption(txt_path: Path | None) -> str | None:
    """The sidecar caption text, or None when there is no sidecar / it's empty.
    None means "deliver the reel caption-less" (no caption to attach, no
    follow-up)."""
    if txt_path is None:
        return None
    text = txt_path.read_text(encoding="utf-8").strip()
    return text or None


def plan_caption(caption: str | None) -> tuple[str | None, str | None]:
    """The caption-cap branch (pure). Returns (doc_caption, followup_message):

      caption is None/empty  -> (None, None)        reel ships caption-less
      len <= 1024            -> (caption, None)      caption attached to the document
      len  > 1024            -> (None, caption)      caption-less doc + follow-up message

    The 1024 boundary is inclusive (exactly 1024 attaches; 1025 splits) — Telegram's
    media-caption cap is 1024 and the sendMessage follow-up covers the overflow."""
    if not caption:
        return (None, None)
    if len(caption) <= TELEGRAM_CAPTION_LIMIT:
        return (caption, None)
    return (None, caption)


# ---------------------------------------------------------------------------
# I/O shell — Telegram POSTs + file moves.
# ---------------------------------------------------------------------------


def _telegram_credentials() -> tuple[str, str]:
    """(token, chat_id) from the environment. Raises loudly when either is unset
    — a missing credential must fail the run, not silently no-op a delivery.

    Imports scrapers.common.db lazily for its import-time load_dotenv() (pulls
    TELEGRAM_* from .env into os.environ); a late import keeps the pure core
    test-importable without the psycopg env (same posture as ig_spotlight.run)."""
    from scrapers.common import db  # noqa: F401  -- import-time .env load only

    try:
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        chat_id = os.environ["TELEGRAM_CHAT_ID"]
    except KeyError as e:
        raise KeyError(
            f"{e.args[0]} is not set. Add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to "
            f".env (Jon sets the real values in his own terminal). --dry-run needs "
            f"neither."
        ) from None
    return token, chat_id


def send_document(token: str, chat_id: str, mp4_path: Path, caption: str | None) -> None:
    """POST a reel as a document (full quality — NOT sendVideo, which recompresses).
    Direct requests.post + raise_for_status so a non-2xx fails the run loud (mirrors
    cohort_signal.post_slack's posture)."""
    import requests

    url = API_BASE.format(token=token, method="sendDocument")
    data = {"chat_id": chat_id}
    if caption is not None:
        data["caption"] = caption
    with open(mp4_path, "rb") as fh:
        resp = requests.post(url, data=data, files={"document": fh}, timeout=120)
    resp.raise_for_status()


def send_message(token: str, chat_id: str, text: str) -> None:
    """POST a text message (the over-length-caption follow-up). raise_for_status
    fails loud on non-2xx."""
    import requests

    url = API_BASE.format(token=token, method="sendMessage")
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
    resp.raise_for_status()


def deliver_pair(token: str, chat_id: str, pair: ReelPair) -> None:
    """Deliver one reel: sendDocument (caption attached when <= 1024), then a
    follow-up sendMessage carrying the full caption when it overflowed."""
    caption = read_caption(pair.txt)
    doc_caption, followup = plan_caption(caption)
    send_document(token, chat_id, pair.mp4, doc_caption)
    if followup is not None:
        send_message(token, chat_id, followup)


def move_to_delivered(pair: ReelPair, delivered_dir: Path) -> None:
    """Move a successfully-delivered pair into build/reels/delivered/ so a re-run
    won't re-send it (idempotence). The .txt moves only when it exists."""
    delivered_dir.mkdir(parents=True, exist_ok=True)
    pair.mp4.replace(delivered_dir / pair.mp4.name)
    if pair.txt is not None and pair.txt.is_file():
        pair.txt.replace(delivered_dir / pair.txt.name)


def run(reel_dir: str | Path = DEFAULT_REEL_DIR, dry_run: bool = False) -> int:
    """Pair, deliver, and clear every PAIRED reel in reel_dir. Empty dir = clean
    no-op, exit 0. --dry-run prints the plan (and reads no credentials).

    Pair-gate (CTK-176): only an .mp4 WITH its caption sidecar (.txt) is delivered.
    render_batch always emits the sidecar on a successful render, so a caption-less
    .mp4 in the dir is a stray (a sample/experimental render, e.g. the CTK-164/172/
    173 kinetic-card renders that share build/reels/), not a daily reel — it is
    skipped + logged, never shipped and never moved aside. A dir with only strays
    is therefore a no-op too."""
    pairs = pair_reels(reel_dir)
    if not pairs:
        print(f"ig-deliver: no reels in {reel_dir} — nothing to deliver (no-op).")
        return 0

    deliverable = [p for p in pairs if p.txt is not None]
    for p in pairs:
        if p.txt is None:
            print(
                f"ig-deliver: skipping {p.mp4.name} — no caption sidecar (.txt); "
                f"not a daily reel (left in place).",
                file=sys.stderr,
            )

    if not deliverable:
        print(f"ig-deliver: no paired reels in {reel_dir} — nothing to deliver (no-op).")
        return 0

    if dry_run:
        for pair in deliverable:
            doc_caption, followup = plan_caption(read_caption(pair.txt))
            cap_note = (
                "no caption" if doc_caption is None and followup is None
                else f"caption attached ({len(doc_caption)} chars)" if doc_caption is not None
                else f"caption-less doc + follow-up message ({len(followup)} chars)"
            )
            print(f"ig-deliver [dry-run]: would send {pair.mp4.name} via sendDocument — {cap_note}")
        print(f"ig-deliver [dry-run]: {len(deliverable)} reel(s); nothing POSTed, nothing moved.")
        return 0

    token, chat_id = _telegram_credentials()
    delivered_dir = Path(reel_dir) / DELIVERED_SUBDIR
    for pair in deliverable:
        deliver_pair(token, chat_id, pair)
        move_to_delivered(pair, delivered_dir)
        print(f"ig-deliver: delivered {pair.mp4.name} -> Telegram; moved to {delivered_dir}.")

    print(f"ig-deliver: delivered {len(deliverable)} reel(s) to the Telegram chat.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reel-dir", default=DEFAULT_REEL_DIR,
                        help="Dir holding the rendered reels + caption sidecars.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would send without POSTing (needs no credentials).")
    args = parser.parse_args()
    try:
        return run(args.reel_dir, dry_run=args.dry_run)
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1 (loud-failure posture)
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
