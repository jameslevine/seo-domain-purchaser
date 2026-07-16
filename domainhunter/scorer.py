"""Composite 0-100 scorer for content-site-rebuild domains.

ED.net can only sort by one column; this is where the multi-factor ranking happens.
Four buckets (weights from config, default 35/25/20/20):

  authority      — link power: Trust Flow, referring domains, Wikipedia/.edu/.gov links
  cleanliness    — non-manipulated profile: TR ratio (CF/TF, lower better) + topic coherence
  history        — rebuildability: archive age + archive crawl-result depth
  latent_traffic — live demand: SEMrush organic keywords + traffic + search volume

Each bucket produces a 0..1 sub-score, multiplied by its weight; total rounded to 0..100.
"""

from __future__ import annotations

import math

from .models import Candidate

DEFAULT_WEIGHTS = {"authority": 35, "cleanliness": 25, "history": 20, "latent_traffic": 20}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _authority_subscore(c: Candidate) -> float:
    # Trust Flow: TF of ~40 is excellent for a dropped domain; scale toward 1.0 there.
    tf = _clamp01(c.trust_flow / 40.0)
    # Referring domains: log scale; ~500 ref domains ≈ full marks.
    rd = _clamp01(math.log10(c.referring_domains + 1) / math.log10(500 + 1))
    # Trust signals: Wikipedia + .edu/.gov referring domains are rare and valuable.
    trust_links = (1 if c.wikipedia_links > 0 else 0) * 0.4
    trust_links += _clamp01((c.edu_refdomains + c.gov_refdomains) / 10.0) * 0.6
    return _clamp01(0.5 * tf + 0.35 * rd + 0.15 * trust_links)


def _cleanliness_subscore(c: Candidate, spam_topics: list[str]) -> float:
    # Trust ratio TR = CF/TF. <=1.0 is healthy; climbs toward manipulated as it rises.
    if c.trust_ratio <= 0:
        ratio_score = 0.5  # unknown -> neutral
    elif c.trust_ratio <= 1.0:
        ratio_score = 1.0
    else:
        ratio_score = _clamp01(1.0 - (c.trust_ratio - 1.0) / 1.5)  # TR 2.5 -> 0
    # Topic coherence: a single dominant topic (high %) = a real, focused site.
    coherence = 0.5
    if c.topical_trust_flow:
        coherence = _clamp01(c.topical_trust_flow[0].percent / 100.0)
    # Spam-topic penalty.
    dominant = c.dominant_topic.lower()
    spam_penalty = 1.0
    for t in spam_topics:
        if t.lower() in dominant:
            spam_penalty = 0.1
            break
    return _clamp01((0.6 * ratio_score + 0.4 * coherence) * spam_penalty)


def _history_subscore(c: Candidate) -> float:
    # Archive age: 15+ years ≈ full marks.
    age = _clamp01(c.archive_age_years / 15.0)
    # Archive crawl-result depth: 500+ saved crawls = lots of real content history.
    acr = _clamp01(math.log10(c.archive_crawl_results + 1) / math.log10(500 + 1))
    return _clamp01(0.6 * age + 0.4 * acr)


def _latent_traffic_subscore(c: Candidate) -> float:
    # Organic keywords: 1000+ ≈ full marks (log scale).
    kw = _clamp01(math.log10(c.organic_keywords + 1) / math.log10(1000 + 1))
    # Organic traffic: 5000+/mo ≈ full marks.
    traf = _clamp01(math.log10(c.organic_traffic + 1) / math.log10(5000 + 1))
    # Search volume on the name: minor signal.
    sv = _clamp01(math.log10(c.search_volume + 1) / math.log10(10000 + 1))
    return _clamp01(0.45 * kw + 0.45 * traf + 0.10 * sv)


def score_candidate(c: Candidate, scoring_cfg: dict) -> Candidate:
    """Compute and attach the composite score + per-bucket breakdown to a Candidate."""
    weights = {**DEFAULT_WEIGHTS, **scoring_cfg.get("weights", {})}
    spam_topics = scoring_cfg.get("spam_topics", [])

    subs = {
        "authority": _authority_subscore(c),
        "cleanliness": _cleanliness_subscore(c, spam_topics),
        "history": _history_subscore(c),
        "latent_traffic": _latent_traffic_subscore(c),
    }
    breakdown = {k: round(subs[k] * weights[k], 1) for k in subs}
    c.score_breakdown = breakdown
    c.score = round(sum(breakdown.values()))
    return c


def score_all(candidates: list[Candidate], scoring_cfg: dict) -> list[Candidate]:
    for c in candidates:
        score_candidate(c, scoring_cfg)
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
