"""Client for expireddomains.net member area: login, apply filter, paginate results.

Replicates the mechanics validated by hand (see memory/expireddomains-net-mechanics):
  - Login is a POST to /logincheck/ with fields login/password/rememberme.
  - The list filter form is POST-only and stored in the session. GET params only pre-fill,
    so we POST the filter once with button_submit=Apply Filter, then GET subsequent pages.
  - Archive-birth-year MAX maps to form field `fabirth_year` (its name is misleading).
"""

from __future__ import annotations

import logging
import time

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE = "https://www.expireddomains.net"
MEMBER = "https://member.expireddomains.net"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class LoginError(RuntimeError):
    pass


class EdnetClient:
    def __init__(self, username: str, password: str, *, request_delay: float = 1.5):
        self.username = username
        self.password = password
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    # -- auth ---------------------------------------------------------------
    def login(self) -> None:
        # Prime cookies by fetching the login page first.
        self.session.get(f"{BASE}/login/", timeout=30)
        resp = self.session.post(
            f"{BASE}/logincheck/",
            data={"login": self.username, "password": self.password, "rememberme": "1"},
            headers={"Referer": f"{BASE}/login/"},
            timeout=30,
            allow_redirects=True,
        )
        # A successful login lands in the member area and shows the username.
        if "member.expireddomains.net" not in resp.url and self.username.lower() not in resp.text.lower():
            raise LoginError(
                "Login to expireddomains.net failed — check EDN_USERNAME / EDN_PASSWORD."
            )
        log.info("Logged in to expireddomains.net as %s", self.username)

    # -- filtering ----------------------------------------------------------
    def _build_filter_payload(self, flt: dict) -> dict:
        """Translate config 'filter' block into ED.net form fields."""
        payload: dict[str, str] = {"button_submit": "Apply Filter"}

        if flt.get("archive_birth_year_max"):
            # NOTE: fabirth_year is the MAX box (born on/before this year). See memory note.
            payload["fabirth_year"] = str(flt["archive_birth_year_max"])
        if flt.get("name_length_max"):
            payload["fmaxhost"] = str(flt["name_length_max"])
        if flt.get("no_numbers"):
            payload["fnumhost"] = "1"
        if flt.get("no_hyphens"):
            payload["fsephost"] = "1"
        if flt.get("no_adult"):
            payload["fadult"] = "1"
        if flt.get("trust_flow_min") is not None:
            payload["fmseotf"] = str(flt["trust_flow_min"])
        if flt.get("citation_flow_min") is not None:
            payload["fmseocf"] = str(flt["citation_flow_min"])
        if flt.get("referring_domains_min") is not None:
            payload["fmseorefdomains"] = str(flt["referring_domains_min"])
        if flt.get("organic_keywords_min"):
            payload["fsruskmin"] = str(flt["organic_keywords_min"])
        if flt.get("only_available"):
            payload["fwhois"] = "1"
        return payload

    def apply_filter(self, list_slug: str, flt: dict) -> None:
        """POST the filter to the list so the session stores it."""
        url = f"{MEMBER}/domains/{list_slug}/"
        payload = self._build_filter_payload(flt)
        params = {}
        if flt.get("sort_field"):
            params["o"] = flt["sort_field"]
            params["r"] = "desc" if flt.get("sort_desc", True) else "asc"
        # First GET pre-fills the form & ensures we have a session on this list page.
        self.session.get(url, params=params, timeout=30)
        time.sleep(self.request_delay)
        resp = self.session.post(url, data=payload, params=params, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        log.info("Applied filter to %s (%d fields)", list_slug, len(payload) - 1)

    def fetch_pages(self, list_slug: str, flt: dict, max_pages: int = 6) -> list[str]:
        """Yield the HTML of each result page (25 rows each) up to max_pages.

        ED.net paginates with a `start` offset (0, 25, 50, ...). The filter is already
        stored in the session, so these are plain GETs.
        """
        url = f"{MEMBER}/domains/{list_slug}/"
        params_base = {}
        if flt.get("sort_field"):
            params_base["o"] = flt["sort_field"]
            params_base["r"] = "desc" if flt.get("sort_desc", True) else "asc"

        pages: list[str] = []
        for i in range(max_pages):
            params = {**params_base, "start": i * 25}
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            pages.append(resp.text)
            # Stop early if a page has no data rows.
            if 'class="field_domain"' not in resp.text:
                log.info("No more rows at page %d; stopping pagination.", i + 1)
                break
            time.sleep(self.request_delay)
        return pages
