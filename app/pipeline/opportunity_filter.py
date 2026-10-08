"""Heuristic gate: does an ingested item look like a real opportunity?

Noisy feeds (a blog/news RSS) mix articles in with opportunities, which then
clutter the approval queue. This keeps obvious articles out. It's deliberately
conservative:

* A source can *vouch* for its whole feed by setting ``config.default_kind``
  (e.g. ``"job"``) or ``config.trust_all_items = true`` — useful for a job
  board where titles are role names with no "opportunity" keyword. Those feeds
  pass everything except obvious newsletter/digest noise.
* Otherwise an item must carry an opportunity signal in its title (course,
  certificate, scholarship, internship, …) and not be shaped like an article
  ("How to …", "Why …", "Stop …").

Manual admin submissions bypass this entirely.
"""
from __future__ import annotations

import re

# Single words (matched on word boundaries so "intern" != "internal").
_WORDS = {
    "course", "courses", "certificate", "certificates", "certification",
    "certified", "specialization", "specialisation", "nanodegree", "bootcamp",
    "scholarship", "scholarships", "scholar", "fellowship", "fellowships",
    "fellow", "grant", "grants", "bursary", "internship", "internships",
    "intern", "apprenticeship", "apprenticeships", "traineeship", "program",
    "programme", "programs", "programmes", "training", "diploma", "diplomas",
    "degree", "degrees", "masterclass", "workshop", "workshops", "job", "jobs",
    "hiring", "vacancy", "vacancies", "career", "careers", "funded", "tuition",
}
_PHRASES = (
    "boot camp", "free course", "learning path", "professional certificate",
    "fully funded", "graduate program", "we're hiring", "now hiring",
)
_WORD_RE = re.compile(
    r"\b(?:" + "|".join(sorted((re.escape(w) for w in _WORDS), key=len, reverse=True)) + r")\b"
)

# Titles that start like an article almost never name an opportunity.
_ARTICLE_PREFIX = (
    "how to", "how i", "how we", "why ", "what ", "what'", "whats ", "when ",
    "where ", "a guide", "the guide", "guide to", "stop ", "introducing",
    "meet ", "building ", "build a", "i built", "we built", "my ",
    "an introduction", "understanding ", "exploring ", "is ", "are ",
    "should ", "do you", "does ", "can you",
)
_NEWSLETTER = ("newsletter", "weekly roundup", "weekly digest", " digest", "this week in")


def _has_signal(title: str) -> bool:
    return bool(_WORD_RE.search(title)) or any(p in title for p in _PHRASES)


def looks_like_opportunity(item, source=None) -> bool:
    """True if ``item`` should be staged as a candidate opportunity."""
    cfg = (getattr(source, "config", None) or {}) if source is not None else {}
    title = (getattr(item, "title", "") or "").strip().lower()
    if not title:
        return False
    if cfg.get("default_kind") or cfg.get("trust_all_items"):
        # Operator vouches for the feed: keep all but obvious newsletter noise.
        return not any(m in title for m in _NEWSLETTER)
    if any(title.startswith(p) for p in _ARTICLE_PREFIX):
        return False
    return _has_signal(title)
