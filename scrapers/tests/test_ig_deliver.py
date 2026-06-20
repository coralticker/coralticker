"""scrapers/tests/test_ig_deliver.py — CTK-176 unit coverage for the Telegram
daily-reel delivery last-mile (scrapers/tools/ig_deliver.py).

Pure-core tests drive the caption-cap branch and .mp4<->.txt pairing directly;
the I/O-shell tests mock the Telegram POST (a fake `requests` injected into
sys.modules) to assert the sendDocument-not-sendVideo contract, the loud-failure
on non-2xx, the over-length follow-up message, and the move-to-delivered
idempotence. No DB, no network.

Each test is written to FAIL if the guarantee it covers is deleted — the boundary
tests assert both sides of the 1024 cap, the pairing test asserts both the
sidecar-present and sidecar-absent shapes, and the shell tests assert the exact
Telegram method + the file move.

Runnable as:
  python -m scrapers.tests.test_ig_deliver

Coverage:
  test_plan_caption_attaches_at_limit       caption of exactly 1024 attaches to the doc
  test_plan_caption_splits_over_limit       1025 -> caption-less doc + follow-up message
  test_plan_caption_short_attaches          a normal caption attaches
  test_plan_caption_empty_is_caption_less   None/empty -> (None, None)
  test_pair_reels_pairs_sidecar             *.mp4 pairs with its same-stem .txt
  test_pair_reels_missing_sidecar           a reel with no .txt -> txt is None
  test_pair_reels_skips_delivered_subdir    the delivered/ subdir is not re-paired
  test_pair_reels_missing_dir_empty         a missing reel dir -> [] (no-op day)
  test_read_caption_missing_returns_none    no sidecar -> None (deliver caption-less)
  test_run_empty_dir_no_op                  empty dir -> exit 0, no POST, no move
  test_run_skips_caption_less_strays        a caption-less .mp4 is skipped, not shipped/moved (pair-gate)
  test_run_all_strays_no_op                 a dir of only caption-less .mp4s -> exit 0, no POST
  test_send_document_uses_sendDocument      sendDocument endpoint + 'document' file, NOT sendVideo
  test_send_document_attaches_caption       caption rides the sendDocument data
  test_send_document_raises_on_non_2xx      non-2xx -> raises (loud failure)
  test_deliver_pair_over_length_followup    >1024 caption -> sendDocument(no caption) + sendMessage(full)
  test_run_delivers_and_moves              run POSTs each reel then moves the pair to delivered/
  test_run_idempotent_on_rerun             a second run after delivery is a clean no-op
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory

from scrapers.tools import ig_deliver
from scrapers.tools.ig_deliver import (
    TELEGRAM_CAPTION_LIMIT,
    ReelPair,
    pair_reels,
    plan_caption,
    read_caption,
    run,
)


# --- fake Telegram transport ---------------------------------------------

class _FakeResponse:
    def __init__(self, status: int = 200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeRequests:
    """Records every .post call so the shell tests can assert the method + payload.
    Injected into sys.modules['requests'] for the duration of a test."""
    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[dict] = []

    def post(self, url, data=None, json=None, files=None, timeout=None):
        self.calls.append({"url": url, "data": data, "json": json, "files": files})
        return _FakeResponse(self.status)


class _inject_requests:
    """Context manager: swap a _FakeRequests into sys.modules['requests'] so the
    ig_deliver shell's local `import requests` resolves to the fake, then restore."""
    def __init__(self, status: int = 200):
        self.fake = _FakeRequests(status)
        self._saved = None

    def __enter__(self) -> _FakeRequests:
        self._saved = sys.modules.get("requests")
        sys.modules["requests"] = self.fake  # type: ignore[assignment]
        return self.fake

    def __exit__(self, *exc):
        if self._saved is not None:
            sys.modules["requests"] = self._saved
        else:
            del sys.modules["requests"]


def _write_reel(d: Path, stem: str, caption: str | None = None) -> ReelPair:
    """Write a fake .mp4 (+ optional .txt sidecar) and return the pair."""
    mp4 = d / f"{stem}.mp4"
    mp4.write_bytes(b"\x00\x00fake-mp4-bytes")
    txt = None
    if caption is not None:
        txt = d / f"{stem}.txt"
        txt.write_text(caption, encoding="utf-8")
    return ReelPair(mp4=mp4, txt=txt)


# --- caption-cap branch (pure core) --------------------------------------

def test_plan_caption_attaches_at_limit():
    cap = "x" * TELEGRAM_CAPTION_LIMIT  # exactly 1024
    doc_caption, followup = plan_caption(cap)
    assert doc_caption == cap, "1024-char caption must attach to the document"
    assert followup is None, "no follow-up at the inclusive boundary"


def test_plan_caption_splits_over_limit():
    cap = "x" * (TELEGRAM_CAPTION_LIMIT + 1)  # 1025
    doc_caption, followup = plan_caption(cap)
    assert doc_caption is None, "over-limit caption must NOT ride the document"
    assert followup == cap, "the full caption goes as a follow-up message"


def test_plan_caption_short_attaches():
    doc_caption, followup = plan_caption("a normal caption")
    assert doc_caption == "a normal caption"
    assert followup is None


def test_plan_caption_empty_is_caption_less():
    assert plan_caption(None) == (None, None)
    assert plan_caption("") == (None, None)


# --- pairing (pure core) -------------------------------------------------

def test_pair_reels_pairs_sidecar():
    with TemporaryDirectory() as d:
        _write_reel(Path(d), "wwc-101", caption="hello")
        pairs = pair_reels(d)
        assert len(pairs) == 1, pairs
        assert pairs[0].mp4.name == "wwc-101.mp4"
        assert pairs[0].txt is not None and pairs[0].txt.name == "wwc-101.txt"


def test_pair_reels_missing_sidecar():
    with TemporaryDirectory() as d:
        _write_reel(Path(d), "wwc-102", caption=None)  # .mp4 only
        pairs = pair_reels(d)
        assert len(pairs) == 1, pairs
        assert pairs[0].txt is None, "a reel with no .txt must pair to None"


def test_pair_reels_skips_delivered_subdir():
    with TemporaryDirectory() as d:
        base = Path(d)
        _write_reel(base, "wwc-103", caption="x")
        delivered = base / "delivered"
        delivered.mkdir()
        _write_reel(delivered, "wwc-099", caption="old")  # already delivered
        pairs = pair_reels(base)
        names = {p.mp4.name for p in pairs}
        assert names == {"wwc-103.mp4"}, f"delivered/ must be skipped, got {names}"


def test_pair_reels_missing_dir_empty():
    with TemporaryDirectory() as d:
        missing = Path(d) / "does-not-exist"
        assert pair_reels(missing) == [], "a missing reel dir is a no-op, not an error"


def test_read_caption_missing_returns_none():
    assert read_caption(None) is None
    with TemporaryDirectory() as d:
        empty = Path(d) / "blank.txt"
        empty.write_text("   \n", encoding="utf-8")  # whitespace-only
        assert read_caption(empty) is None, "whitespace-only sidecar -> caption-less"


# --- run() no-op (pure-ish: no POST, no credentials) ---------------------

def test_run_empty_dir_no_op():
    with TemporaryDirectory() as d:
        with _inject_requests() as fake:
            rc = run(d, dry_run=False)
        assert rc == 0, "empty dir must exit 0"
        assert fake.calls == [], "empty dir must POST nothing"


def test_run_skips_caption_less_strays():
    # A real (paired) reel alongside a caption-less stray (e.g. a kinetic-card
    # sample sharing build/reels/). The pair-gate ships only the paired one and
    # leaves the stray in place.
    with TemporaryDirectory() as d:
        base = Path(d)
        _write_reel(base, "wwc-501", caption="real reel cap")
        _write_reel(base, "count-up", caption=None)  # stray sample, no sidecar
        os.environ["TELEGRAM_BOT_TOKEN"] = "TOK"
        os.environ["TELEGRAM_CHAT_ID"] = "CHAT"
        try:
            with _inject_requests() as fake:
                rc = run(base, dry_run=False)
        finally:
            del os.environ["TELEGRAM_BOT_TOKEN"]
            del os.environ["TELEGRAM_CHAT_ID"]
        assert rc == 0
        docs = [c for c in fake.calls if c["url"].endswith("/sendDocument")]
        assert len(docs) == 1, "only the paired reel ships, not the caption-less stray"
        # the stray stays put; the paired reel moved out
        assert (base / "count-up.mp4").is_file(), "the stray must be left in place"
        assert not (base / "wwc-501.mp4").is_file(), "the paired reel must move to delivered/"
        assert (base / "delivered" / "wwc-501.mp4").is_file()
        assert not (base / "delivered" / "count-up.mp4").exists(), "a stray must never be moved aside"


def test_run_all_strays_no_op():
    with TemporaryDirectory() as d:
        base = Path(d)
        _write_reel(base, "f8-reveal-plain", caption=None)
        _write_reel(base, "MERGE-SAMPLE", caption=None)
        with _inject_requests() as fake:
            rc = run(base, dry_run=False)  # no credentials needed — nothing ships
        assert rc == 0, "a dir of only caption-less strays is a no-op"
        assert fake.calls == [], "no paired reel -> POST nothing"


# --- I/O shell (mocked Telegram) -----------------------------------------

def test_send_document_uses_sendDocument():
    with TemporaryDirectory() as d:
        pair = _write_reel(Path(d), "wwc-201", caption="cap")
        with _inject_requests() as fake:
            ig_deliver.send_document("TOK", "CHAT", pair.mp4, "cap")
        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["url"].endswith("/sendDocument"), call["url"]
        assert "sendVideo" not in call["url"], "must be sendDocument, never sendVideo"
        assert "document" in (call["files"] or {}), "the mp4 rides the 'document' file part"


def test_send_document_attaches_caption():
    with TemporaryDirectory() as d:
        pair = _write_reel(Path(d), "wwc-202", caption="cap")
        with _inject_requests() as fake:
            ig_deliver.send_document("TOK", "CHAT", pair.mp4, "my caption")
        assert fake.calls[0]["data"]["caption"] == "my caption"
        # caption-less variant carries no caption key
        with _inject_requests() as fake2:
            ig_deliver.send_document("TOK", "CHAT", pair.mp4, None)
        assert "caption" not in fake2.calls[0]["data"]


def test_send_document_raises_on_non_2xx():
    with TemporaryDirectory() as d:
        pair = _write_reel(Path(d), "wwc-203", caption=None)
        raised = False
        with _inject_requests(status=500):
            try:
                ig_deliver.send_document("TOK", "CHAT", pair.mp4, None)
            except RuntimeError:
                raised = True
        assert raised, "a non-2xx Telegram response must raise (loud failure)"


def test_deliver_pair_over_length_followup():
    with TemporaryDirectory() as d:
        long_cap = "y" * (TELEGRAM_CAPTION_LIMIT + 50)
        pair = _write_reel(Path(d), "wwc-204", caption=long_cap)
        with _inject_requests() as fake:
            ig_deliver.deliver_pair("TOK", "CHAT", pair)
        assert len(fake.calls) == 2, "over-length caption -> document + follow-up message"
        doc_call, msg_call = fake.calls
        assert doc_call["url"].endswith("/sendDocument")
        assert "caption" not in (doc_call["data"] or {}), "over-length doc must be caption-less"
        assert msg_call["url"].endswith("/sendMessage")
        assert msg_call["json"]["text"] == long_cap, "the full caption rides the follow-up"


def test_run_delivers_and_moves():
    with TemporaryDirectory() as d:
        base = Path(d)
        _write_reel(base, "wwc-301", caption="cap one")
        _write_reel(base, "tsa-302", caption="cap two")
        os.environ["TELEGRAM_BOT_TOKEN"] = "TOK"
        os.environ["TELEGRAM_CHAT_ID"] = "CHAT"
        try:
            with _inject_requests() as fake:
                rc = run(base, dry_run=False)
        finally:
            del os.environ["TELEGRAM_BOT_TOKEN"]
            del os.environ["TELEGRAM_CHAT_ID"]
        assert rc == 0
        assert len([c for c in fake.calls if c["url"].endswith("/sendDocument")]) == 2
        # source dir cleared, pairs moved into delivered/
        assert list(base.glob("*.mp4")) == [], "delivered reels must leave the source dir"
        delivered = base / "delivered"
        moved = {p.name for p in delivered.glob("*")}
        assert moved == {"wwc-301.mp4", "wwc-301.txt", "tsa-302.mp4", "tsa-302.txt"}, moved


def test_run_idempotent_on_rerun():
    with TemporaryDirectory() as d:
        base = Path(d)
        _write_reel(base, "wwc-401", caption="cap")
        os.environ["TELEGRAM_BOT_TOKEN"] = "TOK"
        os.environ["TELEGRAM_CHAT_ID"] = "CHAT"
        try:
            with _inject_requests() as fake1:
                run(base, dry_run=False)
            assert len(fake1.calls) >= 1
            # second run: nothing left to deliver
            with _inject_requests() as fake2:
                rc2 = run(base, dry_run=False)
        finally:
            del os.environ["TELEGRAM_BOT_TOKEN"]
            del os.environ["TELEGRAM_CHAT_ID"]
        assert rc2 == 0
        assert fake2.calls == [], "a re-run after delivery must POST nothing (idempotent)"


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
