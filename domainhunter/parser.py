"""Parse expireddomains.net result tables into Candidate objects.

Keys off the stable `field_*` CSS classes on each <td> rather than column position,
so it survives column reordering in the Column Manager.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import Candidate, TopicalTrustFlow, parse_date, parse_number, parse_year

BASE_URL = "https://member.expireddomains.net"

# Maps the TTF anchor's title, e.g. "Society/Politics (88.56%)", into topic + percent.
_TTF_RE = re.compile(r"^(.*?)\s*\(([\d.]+)%\)\s*$")


def _cell_text(row, field_class: str) -> str:
    td = row.find("td", class_=field_class)
    return td.get_text(strip=True) if td else ""


def _parse_topical_trust_flow(row) -> list[TopicalTrustFlow]:
    td = row.find("td", class_="field_majesticseo_topicaltrustflow")
    if not td:
        return []
    out: list[TopicalTrustFlow] = []
    for a in td.find_all("a"):
        title = a.get("title", "")
        m = _TTF_RE.match(title)
        if not m:
            continue
        out.append(
            TopicalTrustFlow(
                topic=m.group(1).strip(),
                percent=float(m.group(2)),
                value=int(parse_number(a.get_text(strip=True))),
            )
        )
    return out


def _parse_status(row) -> str:
    """Status for the domain's own TLD on the deleted lists ('available'/'registered')."""
    # On pending-delete there's no single status column; we read the per-TLD status that
    # matches the domain's own extension when present, else blank.
    domain = _cell_text(row, "field_domain")
    tld = domain.rsplit(".", 1)[-1].lower() if "." in domain else ""
    td = row.find("td", class_=f"field_status{tld}")
    if td:
        span = td.find("span")
        if span:
            return span.get_text(strip=True)
    return ""


def _parse_backorder_links(row) -> dict[str, str]:
    """Extract provider -> absolute backorder URL from the row's link menus.

    ED.net marks backorder anchors with `favXXX` classes and a 'Backorder at <Provider>'
    title. The href is a /goto/ redirect that resolves to the provider's backorder page.
    """
    links: dict[str, str] = {}
    for a in row.find_all("a", title=re.compile(r"^Backorder at ", re.IGNORECASE)):
        provider = a.get("title", "").replace("Backorder at ", "").strip()
        href = a.get("href", "")
        if provider and href and href != "#":
            links.setdefault(provider, urljoin(BASE_URL, href))
    return links


def parse_rows(html: str) -> list[Candidate]:
    """Parse all data rows in a listing-table HTML blob into Candidates."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="base1") or soup
    candidates: list[Candidate] = []

    for row in table.select("tbody tr"):
        domain_td = row.find("td", class_="field_domain")
        if not domain_td:
            continue
        name_link = domain_td.find("a", class_="namelinks") or domain_td.find("a")
        if not name_link:
            continue
        # The link's title attribute preserves original casing of the domain.
        domain = (name_link.get("title") or name_link.get_text(strip=True)).strip().lower()
        if not domain or "." not in domain:
            continue

        length = _cell_text(row, "field_length")
        c = Candidate(
            domain=domain,
            trust_flow=parse_number(_cell_text(row, "field_majesticseo_tf")),
            citation_flow=parse_number(_cell_text(row, "field_majesticseo_cf")),
            trust_ratio=parse_number(_cell_text(row, "field_majesticseo_tr")),
            referring_domains=parse_number(_cell_text(row, "field_majesticseo_domainpop")),
            backlinks=parse_number(_cell_text(row, "field_bl")),
            wikipedia_links=parse_number(_cell_text(row, "field_wikipedia_links")),
            edu_refdomains=parse_number(_cell_text(row, "field_majesticseo_edudomainpop")),
            gov_refdomains=parse_number(_cell_text(row, "field_majesticseo_govdomainpop")),
            archive_birth_year=parse_year(_cell_text(row, "field_abirth")),
            archive_crawl_results=parse_number(_cell_text(row, "field_aentries")),
            whois_creation_year=parse_year(_cell_text(row, "field_creationdate")),
            organic_keywords=parse_number(_cell_text(row, "field_semrush_us_organic_keywords")),
            organic_traffic=parse_number(_cell_text(row, "field_semrush_us_organic_traffic")),
            search_volume=parse_number(_cell_text(row, "field_searchesglobal")),
            topical_trust_flow=_parse_topical_trust_flow(row),
            end_date=parse_date(_cell_text(row, "field_enddate")),
            add_date=parse_date(_cell_text(row, "field_adddate")),
            length=int(length) if length.isdigit() else None,
            status=_parse_status(row),
            backorder_links=_parse_backorder_links(row),
        )
        candidates.append(c)

    return candidates


def parse_result_count(html: str) -> int | None:
    """Pull the 'About N Domains' total from a listing page, if present."""
    m = re.search(r"About\s+([\d,]+)\s+Domains", html)
    return int(m.group(1).replace(",", "")) if m else None
