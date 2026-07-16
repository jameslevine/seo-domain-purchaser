"""Domain Hunter pipeline entry point.

Flow: login -> apply filter -> scrape pages -> parse -> score/rank -> dedupe
      -> Wayback spam-check top-N -> render email -> send (or preview on --dry-run).

Usage:
    python -m domainhunter.main --dry-run        # scrape, score, write HTML preview, send nothing
    python -m domainhunter.main                  # full run, sends the email
    python -m domainhunter.main --limit 10       # cap email to top 10
    python -m domainhunter.main --from-fixture tests/fixtures/pendingdelete_sample.html --dry-run
    python -m domainhunter.main --no-wayback     # skip archive.org checks (faster)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_settings
from .emailer import render_email, send_email, write_preview
from .parser import parse_result_count, parse_rows
from .scorer import score_all
from .state import SeenStore
from .wayback import WaybackChecker

log = logging.getLogger("domainhunter")


def _gather_pages(args, settings) -> tuple[list[str], bool]:
    """Return (list_of_page_html, is_live). Uses a fixture if requested."""
    if args.from_fixture:
        html = Path(args.from_fixture).read_text()
        return [html], False
    # Live: import here so a fixture run needs no network/creds wiring.
    from .ednet_client import EdnetClient

    client = EdnetClient(settings.creds.edn_username, settings.creds.edn_password)
    client.login()
    flt = settings.filter
    client.apply_filter(settings.list_slug, flt)
    pages = client.fetch_pages(settings.list_slug, flt, max_pages=flt.get("max_pages", 6))
    return pages, True


def run(args) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings(args.config, require_email=not (args.dry_run or args.from_fixture))

    # 1. Gather + parse -----------------------------------------------------
    pages, is_live = _gather_pages(args, settings)
    candidates = []
    filtered_total = None
    for html in pages:
        if filtered_total is None:
            filtered_total = parse_result_count(html)
        candidates.extend(parse_rows(html))
    log.info("Parsed %d candidates from %d page(s)", len(candidates), len(pages))
    if not candidates:
        log.warning("No candidates parsed — nothing to do.")
        return 0

    # 2. Score + rank -------------------------------------------------------
    score_all(candidates, settings.scoring)

    # 3. Dedupe against prior runs -----------------------------------------
    store = SeenStore(settings.state_db_path())
    suppress_days = settings.state.get("suppress_days", 30)
    fresh = []
    for c in candidates:
        store.record_seen(c.domain, c.score)
        if store.is_suppressed(c.domain, suppress_days):
            log.debug("Suppressing %s (emailed within %dd)", c.domain, suppress_days)
            continue
        fresh.append(c)
    log.info("%d candidates after dedupe (suppressed %d)", len(fresh), len(candidates) - len(fresh))

    # 4. Trim to top-N, then Wayback-check just those ----------------------
    top_n = args.limit or settings.email.get("top_n", 25)
    shortlist = fresh[:top_n]

    if not args.no_wayback:
        wb = WaybackChecker(settings.wayback)
        wb.check_top(shortlist)
        # Demote (don't drop) flagged domains to the bottom so clean ones lead.
        shortlist.sort(key=lambda c: (c.wayback_flag, -c.score))

    # 5. Render -------------------------------------------------------------
    if not shortlist:
        log.warning("Nothing fresh to email today.")
        return 0
    html = render_email(
        shortlist,
        list_slug=settings.list_slug,
        subject_prefix=settings.email.get("subject_prefix", "[Domain Hunter]"),
        preferred_backorder=settings.email.get("preferred_backorder", []),
        filtered_total=filtered_total,
    )
    subject = f"{settings.email.get('subject_prefix', '[Domain Hunter]')} {len(shortlist)} domains to snipe"

    # 6. Send or preview ----------------------------------------------------
    if args.dry_run:
        path = write_preview(html)
        log.info("DRY RUN — wrote preview to %s (no email sent)", path)
        print(f"\nTop {len(shortlist)} candidates:")
        for i, c in enumerate(shortlist, 1):
            flag = "  ⚠ " + c.wayback_note if c.wayback_flag else ""
            print(f"  {i:>2}. {c.score:>3}  {c.domain:28} TF={c.trust_flow:.0f} RD={c.referring_domains:.0f}{flag}")
        print(f"\nPreview: {path}")
    else:
        send_email(html, subject=subject, creds=settings.creds)
        store.mark_emailed([c.domain for c in shortlist])
        log.info("Emailed %d domains and recorded them in the dedupe store.", len(shortlist))

    store.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Find, score, and email a snipe list of expiring SEO domains.")
    p.add_argument("--config", default=None, help="Path to config.yaml")
    p.add_argument("--dry-run", action="store_true", help="Scrape & score but send no email; write an HTML preview.")
    p.add_argument("--from-fixture", default=None, help="Parse a saved HTML file instead of going live.")
    p.add_argument("--limit", type=int, default=None, help="Cap the email to the top N domains.")
    p.add_argument("--no-wayback", action="store_true", help="Skip archive.org spam-history checks.")
    p.add_argument("--verbose", action="store_true", help="Debug logging.")
    args = p.parse_args()
    try:
        return run(args)
    except Exception as e:  # noqa: BLE001 — top-level guard for cron friendliness
        log.error("Run failed: %s", e, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
