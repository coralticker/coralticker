"""One-off F7 render excluding over-featured vendors (wwc, aquasd) from the
DISPLAYED SAMPLE. Cover true_count stays the honest full-population figure across
all vendors (honest-count canon, CTK-191/195) — only the slide cards are curated.
Mirrors content_cards.build_f7. Out: build/cards/f7-arrivals.mp4."""
from datetime import datetime, timezone
from pathlib import Path

from scrapers.common.db import get_conn
from scrapers.tools import content_queries as cq
from scrapers.tools import data_card
from scrapers.tools.content_cards import _CLOSER_LINE, _OUT_NAME

EXCLUDE = {"wwc", "aquasd"}
OUT_DIR = "build/cards"

with get_conn() as conn:
    true_count, composition, items = cq.select_f7_arrivals(conn, exclude_vendors=EXCLUDE)
    print(f"cover true_count={true_count}  composition={composition}  cards={len(items)}")
    for i, it in enumerate(items):
        print(f"  {i+1}. {it['vendor']:28} {it['name']}")
    if not items:
        raise SystemExit("no items after exclude — aborting")
    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    out = data_card.render_f7_arrivals(
        count=true_count,
        composition=composition,
        items=items,
        now=datetime.now(timezone.utc),
        closer_line=_CLOSER_LINE,
        out_path=Path(OUT_DIR) / _OUT_NAME["f7"],
    )
    print(f"rendered -> {out}")
