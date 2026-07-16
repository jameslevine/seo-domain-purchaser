"""Wayback Machine spam-history check — automates the manual 'sniff test'.

For a candidate, query the archive.org CDX API for its historical snapshots, sample a few
spread across its lifetime, fetch their archived HTML, and scan for spam markers (pharma,
casino, adult, gambling, etc.). Flags the domain (does NOT auto-drop) so the email can warn.
"""

from __future__ import annotations

import logging
import time

import requests

from .models import Candidate

log = logging.getLogger(__name__)

CDX_API = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_URL = "https://web.archive.org/web/{timestamp}id_/{original}"
USER_AGENT = "domain-hunter/0.1 (research; contact set in config)"


class WaybackChecker:
    def __init__(self, cfg: dict):
        self.enabled = cfg.get("enabled", True)
        self.max_candidates = cfg.get("max_candidates_checked", 40)
        self.snapshots_sampled = cfg.get("snapshots_sampled", 6)
        self.timeout = cfg.get("request_timeout", 20)
        self.retries = cfg.get("retries", 3)
        self.markers = [m.lower() for m in cfg.get("spam_markers", [])]
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _get_with_retry(self, url: str, **kwargs):
        """GET with exponential backoff. archive.org commonly returns transient 503s."""
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                if resp.status_code == 200:
                    return resp
                # 429/503 are transient; back off and retry.
                if resp.status_code in (429, 502, 503, 504):
                    last_exc = requests.HTTPError(f"{resp.status_code} transient")
                else:
                    return resp
            except requests.RequestException as e:
                last_exc = e
            time.sleep(2 ** attempt)  # 1s, 2s, 4s
        if last_exc:
            raise last_exc
        return None

    def _list_snapshots(self, domain: str) -> list[str]:
        """Return a time-spread sample of snapshot timestamps for the domain."""
        try:
            resp = self._get_with_retry(
                CDX_API,
                params={
                    "url": domain,
                    "output": "json",
                    "fl": "timestamp,statuscode,mimetype",
                    "filter": "statuscode:200",
                    "collapse": "timestamp:6",  # ~one per month
                    "limit": 2000,
                },
            )
            resp.raise_for_status()
            rows = resp.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("CDX lookup failed for %s after retries: %s", domain, e)
            return []
        if not rows or len(rows) < 2:
            return []
        data = rows[1:]  # first row is the header
        timestamps = [r[0] for r in data if len(r) > 0]
        if not timestamps:
            return []
        # Evenly sample across the captured lifetime.
        n = min(self.snapshots_sampled, len(timestamps))
        step = max(1, len(timestamps) // n)
        return timestamps[::step][:n]

    def _snapshot_has_spam(self, domain: str, timestamp: str) -> tuple[bool, str]:
        url = SNAPSHOT_URL.format(timestamp=timestamp, original=f"http://{domain}/")
        try:
            resp = self._get_with_retry(url)
            if resp is None or resp.status_code != 200:
                return False, ""
            text = resp.text.lower()
        except requests.RequestException:
            return False, ""
        for marker in self.markers:
            if marker in text:
                return True, marker
        return False, ""

    def check(self, candidate: Candidate) -> Candidate:
        """Run the full check on one candidate, setting wayback_flag / wayback_note."""
        if not self.enabled:
            return candidate
        snapshots = self._list_snapshots(candidate.domain)
        if not snapshots:
            candidate.wayback_note = "no archive snapshots found"
            return candidate
        for ts in snapshots:
            is_spam, marker = self._snapshot_has_spam(candidate.domain, ts)
            time.sleep(0.3)  # be polite to archive.org
            if is_spam:
                candidate.wayback_flag = True
                year = ts[:4]
                candidate.wayback_note = f"spam marker '{marker}' found in {year} snapshot"
                log.info("Wayback FLAG %s: %s", candidate.domain, candidate.wayback_note)
                return candidate
        candidate.wayback_note = f"clean across {len(snapshots)} sampled snapshots"
        return candidate

    def check_top(self, candidates: list[Candidate]) -> list[Candidate]:
        """Check only the top-N (by current order) to bound archive.org requests."""
        if not self.enabled:
            return candidates
        for c in candidates[: self.max_candidates]:
            self.check(c)
        return candidates
