"""Data model for a candidate domain and helpers for parsing ED.net's number formats."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date


def parse_number(text: str | None) -> float:
    """Parse ED.net's compact numbers: '6.9 K' -> 6900, '1.5 M' -> 1500000, '-' -> 0."""
    if not text:
        return 0.0
    s = text.strip().replace(",", "")
    if s in ("", "-", "n/a"):
        return 0.0
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*([KMB])?$", s, re.IGNORECASE)
    if not m:
        # Fall back to extracting the first number if there's stray text.
        m2 = re.search(r"[0-9]*\.?[0-9]+", s)
        return float(m2.group()) if m2 else 0.0
    value = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    return value * {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]


def parse_year(text: str | None) -> int | None:
    """Parse a 4-digit year from a cell like '2002'."""
    if not text:
        return None
    m = re.search(r"(19|20)\d{2}", text)
    return int(m.group()) if m else None


def parse_date(text: str | None) -> date | None:
    """Parse an ISO date like '2026-06-18'."""
    if not text:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


@dataclass
class TopicalTrustFlow:
    """One Majestic Topical Trust Flow entry, e.g. ('Society/Politics', 88.56, 21)."""

    topic: str
    percent: float
    value: int


@dataclass
class Candidate:
    """A single domain row scraped from a list, plus everything derived from it."""

    domain: str

    # Authority
    trust_flow: float = 0.0
    citation_flow: float = 0.0
    trust_ratio: float = 0.0            # CF/TF as reported by ED.net (lower is healthier)
    referring_domains: float = 0.0      # MDP
    backlinks: float = 0.0
    wikipedia_links: float = 0.0
    edu_refdomains: float = 0.0
    gov_refdomains: float = 0.0

    # History
    archive_birth_year: int | None = None
    archive_crawl_results: float = 0.0  # ACR
    whois_creation_year: int | None = None

    # Latent traffic / demand
    organic_keywords: float = 0.0       # SEMrush US
    organic_traffic: float = 0.0        # SEMrush US
    search_volume: float = 0.0          # Google Ads global monthly

    # Topical trust flow (parsed from the TTF cell title attributes)
    topical_trust_flow: list[TopicalTrustFlow] = field(default_factory=list)

    # Listing meta
    end_date: date | None = None        # pending-delete drop date
    add_date: date | None = None
    length: int | None = None
    status: str = ""                    # 'available' / 'registered' on deleted lists
    backorder_links: dict[str, str] = field(default_factory=dict)  # provider -> absolute URL

    # Derived (filled by scorer / wayback)
    score: int = 0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    wayback_flag: bool = False
    wayback_note: str = ""

    @property
    def archive_age_years(self) -> int:
        if not self.archive_birth_year:
            return 0
        return max(0, date.today().year - self.archive_birth_year)

    @property
    def dominant_topic(self) -> str:
        return self.topical_trust_flow[0].topic if self.topical_trust_flow else ""

    @property
    def days_until_drop(self) -> int | None:
        if not self.end_date:
            return None
        return (self.end_date - date.today()).days

    def preferred_backorder(self, priority: list[str]) -> tuple[str, str] | None:
        """Return (provider, url) for the highest-priority available backorder link."""
        for provider in priority:
            if provider in self.backorder_links:
                return provider, self.backorder_links[provider]
        # Otherwise return any link we have.
        for provider, url in self.backorder_links.items():
            return provider, url
        return None
