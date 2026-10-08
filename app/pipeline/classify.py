"""Classify an opportunity into (category, difficulty, summary).

Heuristic by default (deterministic, no API key). Optionally upgraded by an
LLM via ``llm.py`` when ``LLM_PROVIDER`` + key are configured. The LLM only
ever *upgrades* a validated result; on any failure we fall back to heuristic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import settings
from ..models import CATEGORIES, Difficulty

logger = logging.getLogger("veloxi.classify")

# Weighted keyword scorecard per category.
_CATEGORY_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "Cybersecurity": [
        ("cybersecurity", 5), ("cyber security", 5), ("security", 3), ("cyber", 3),
        ("soc", 3), ("siem", 3), ("threat", 3), ("penetration", 4), ("pentest", 4),
        ("ethical hacking", 5), ("comptia security", 5), ("malware", 3), ("ransomware", 3),
    ],
    "Cloud Computing": [
        ("aws", 4), ("azure", 4), ("gcp", 4), ("google cloud", 4), ("cloud", 3),
        ("kubernetes", 4), ("terraform", 4), ("ec2", 3), ("s3", 3), ("devops", 3),
        ("docker", 3), ("serverless", 3), ("cloud practitioner", 5),
    ],
    "Data & AI": [
        ("machine learning", 5), ("deep learning", 5), ("data analytics", 5),
        ("data science", 5), ("data analyst", 4), ("artificial intelligence", 5),
        (" ai ", 3), ("ml ", 3), ("pandas", 3), ("analytics", 3), ("power bi", 4),
        ("statistics", 3), ("neural", 3), ("llm", 4), ("data", 2),
    ],
    "Software Development": [
        ("programming", 4), ("software", 3), ("web development", 5), ("full stack", 5),
        ("front-end", 4), ("front end", 4), ("frontend", 4), ("backend", 4),
        ("javascript", 4), ("python", 3), ("java ", 3), ("react", 4), ("algorithms", 4),
        ("cs50", 5), ("responsive web", 5), ("developer", 3), ("coding", 3),
    ],
    "Design": [
        ("ux design", 5), ("ui design", 5), (" ux ", 4), (" ui ", 4), ("figma", 4),
        ("graphic design", 5), ("product design", 5), ("user experience", 5),
        ("visual design", 4), ("design", 2),
    ],
    "Business & PM": [
        ("project management", 5), ("product management", 5), ("pmp", 4), ("scrum", 4),
        ("agile", 4), ("product manager", 4), ("business", 3), ("management", 3),
        ("leadership", 3), ("marketing", 3), ("finance", 3),
    ],
    "IT Support": [
        ("it support", 5), ("help desk", 5), ("helpdesk", 5), ("comptia a+", 5),
        ("networking", 3), ("hardware", 3), ("troubleshoot", 4), ("technical support", 5),
        ("system administration", 4),
    ],
    # ---- Science & Health ----
    "Mathematics": [
        ("mathematics", 5), ("calculus", 5), ("linear algebra", 5), ("algebra", 4),
        ("geometry", 4), ("number theory", 5), ("mathematical", 4), ("probability", 4),
        ("differential equations", 5), ("olympiad", 3), ("putnam", 5),
    ],
    "Physics": [
        ("physics", 5), ("quantum", 5), ("mechanics", 3), ("relativity", 5),
        ("astrophysics", 5), ("particle", 4), ("electromagnetism", 5), ("thermodynamic", 3),
        ("optics", 4), ("cern", 4), ("astronomy", 4),
    ],
    "Chemistry": [
        ("chemistry", 5), ("organic chemistry", 5), ("biochemistry", 4), ("chemical", 4),
        ("spectroscopy", 5), ("molecules", 3), ("polymer", 4), ("analytical chemistry", 5),
    ],
    "Biology": [
        ("biology", 5), ("genetics", 5), ("molecular biology", 5), ("ecology", 5),
        ("microbiology", 5), ("genomics", 5), ("evolution", 4), ("cell biology", 5),
        ("bioinformatics", 4), ("igem", 5), ("synthetic biology", 5),
    ],
    "Medicine": [
        ("medicine", 5), ("medical", 4), ("clinical", 4), ("anatomy", 5),
        ("physiology", 5), ("surgery", 5), ("diagnosis", 4), ("patient care", 5),
        ("nursing", 4), ("usmle", 5),
    ],
    "Pharmacy": [
        ("pharmacy", 5), ("pharmacology", 5), ("pharmaceutical", 5), ("drug discovery", 5),
        ("drug development", 5), ("medicines", 4), ("toxicology", 5),
    ],
    "Public Health": [
        ("public health", 5), ("epidemiology", 5), ("global health", 5),
        ("health policy", 5), ("biostatistics", 5), ("outbreak", 4), ("vaccination", 4),
        ("health systems", 4),
    ],
    "Neuroscience": [
        ("neuroscience", 5), ("neural science", 5), ("brain", 4), ("cognitive", 4),
        ("neurobiology", 5), ("neuroimaging", 5), ("neurology", 5),
    ],
    # ---- Engineering ----
    "Mechanical Engineering": [
        ("mechanical engineering", 5), ("cad", 4), ("solidworks", 5), ("fusion 360", 5),
        ("robotics", 4), ("manufacturing", 4), ("fluid dynamics", 5), ("mechatronics", 5),
        ("automotive", 4),
    ],
    "Electrical Engineering": [
        ("electrical engineering", 5), ("circuits", 5), ("electronics", 5),
        ("embedded systems", 5), ("signal processing", 5), ("power systems", 5),
        ("microcontroller", 5), ("arduino", 4), ("semiconductor", 5),
    ],
    "Civil Engineering": [
        ("civil engineering", 5), ("structural engineering", 5), ("construction", 4),
        ("geotechnical", 5), ("surveying", 4), ("transportation engineering", 5),
        ("concrete", 4), ("infrastructure", 3),
    ],
    "Industrial Engineering": [
        ("industrial engineering", 5), ("supply chain", 5), ("operations research", 5),
        ("lean six sigma", 5), ("six sigma", 5), ("logistics", 4), ("quality management", 4),
        ("process improvement", 4),
    ],
    "Renewable Energy": [
        ("renewable energy", 5), ("solar energy", 5), ("wind energy", 5), ("solar", 4),
        ("photovoltaic", 5), ("sustainable energy", 5), ("energy transition", 5),
        ("green hydrogen", 5), ("energy storage", 4),
    ],
    # ---- Business & Social Sciences ----
    "Marketing": [
        ("marketing", 5), ("digital marketing", 5), ("seo", 4), ("social media marketing", 5),
        ("branding", 4), ("advertising", 4), ("e-commerce", 4), ("content marketing", 5),
    ],
    "Finance": [
        ("finance", 5), ("financial", 4), ("accounting", 5), ("investment", 4),
        ("financial markets", 5), ("valuation", 4), ("cfa", 5), ("banking", 4),
        ("corporate finance", 5),
    ],
    "Economics": [
        ("economics", 5), ("microeconomics", 5), ("macroeconomics", 5), ("econometrics", 5),
        ("economic", 4), ("monetary policy", 5), ("game theory", 4), ("development economics", 5),
    ],
    "Psychology": [
        ("psychology", 5), ("psychological", 5), ("behavioral science", 5),
        ("mental health", 4), ("well-being", 4), ("cognition", 4), ("therapy", 4),
        ("counseling", 4),
    ],
    "Law": [
        ("law", 4), ("legal", 5), ("contract law", 5), ("international law", 5),
        ("human rights", 4), ("intellectual property", 5), ("copyright", 4),
        ("criminal law", 5), ("constitutional", 5),
    ],
    "Education": [
        ("teaching", 5), ("education", 4), ("pedagogy", 5), ("curriculum", 5),
        ("teacher", 4), ("learning how to learn", 5), ("instructional design", 5),
        ("classroom", 4), ("tesol", 5), ("teaching english", 5),
    ],
}

_BEGINNER_SIGNALS = (
    "beginner", "intro", "introduction", "foundations", "fundamentals",
    "getting started", "no experience", "basics", "essentials", "101",
)
_ADVANCED_SIGNALS = ("advanced", "expert", "specialization", "deep dive", "mastery", "professional")
_INTERMEDIATE_SIGNALS = ("intermediate", "associate", "practitioner")

_DEFAULT_CATEGORY = "Software Development"


@dataclass
class Classification:
    category: str
    difficulty: str
    summary: str
    confidence: float = 0.0
    method: str = "heuristic"


def _haystack(title: str, description: str | None) -> str:
    return f" {(title or '').lower()} {(description or '').lower()} "


def heuristic_category(title: str, description: str | None, hint: str | None) -> tuple[str, float]:
    text = _haystack(title, description)
    scores: dict[str, int] = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(weight for term, weight in keywords if term in text)
        if score:
            scores[category] = score
    if not scores:
        if hint in CATEGORIES:
            return hint, 0.3
        return _DEFAULT_CATEGORY, 0.0
    best = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    return best, round(scores[best] / total, 3)


def heuristic_difficulty(title: str, description: str | None) -> str:
    text = _haystack(title, description)
    if any(s in text for s in _ADVANCED_SIGNALS):
        # "professional certificate" is broad/entry-level; don't over-promote it.
        if "professional certificate" in text and not any(
            s in text for s in ("advanced", "expert", "mastery")
        ):
            return Difficulty.beginner.value
        return Difficulty.advanced.value
    if any(s in text for s in _INTERMEDIATE_SIGNALS):
        return Difficulty.intermediate.value
    if any(s in text for s in _BEGINNER_SIGNALS):
        return Difficulty.beginner.value
    return Difficulty.intermediate.value


_SCHOLARSHIP_SIGNALS = (
    "scholarship", "fellowship", "grant", "bursary", "stipend",
    "financial aid", "fully funded", "tuition waiver",
)
_JOB_SIGNALS = (
    "hiring", "vacancy", "we are looking", "remote role", "full-time", "full time",
    "internship", "apply now", "engineer at", "developer at", "(remote)", "job:",
)
_SUMMER_SCHOOL_SIGNALS = ("summer school", "summer programme", "summer program", "winter school")
_CONFERENCE_SIGNALS = ("conference", "symposium", "congress", "laureate forum", "annual meeting")
_COMPETITION_SIGNALS = (
    "competition", "olympiad", "challenge", "hackathon", "contest", "award",
    "decathlon", "tournament",
)
_RESEARCH_SIGNALS = (
    "research experience", "research programme", "research program", "research internship",
    "summer student programme", "reu ", "research opportunity", "research assistant",
)


def infer_kind(title: str, description: str | None = None) -> str:
    """Best-effort kind classification. Most-specific signals win:
    summer_school | conference | competition | research | scholarship | job | course."""
    text = _haystack(title, description)
    if any(s in text for s in _SUMMER_SCHOOL_SIGNALS):
        return "summer_school"
    if any(s in text for s in _CONFERENCE_SIGNALS):
        return "conference"
    if any(s in text for s in _COMPETITION_SIGNALS):
        return "competition"
    if any(s in text for s in _RESEARCH_SIGNALS):
        return "research"
    if any(s in text for s in _SCHOLARSHIP_SIGNALS):
        return "scholarship"
    if any(s in text for s in _JOB_SIGNALS):
        return "job"
    return "course"


def _heuristic_summary(title: str, description: str | None, category: str) -> str:
    if description:
        first = description.strip().split(". ")[0].strip()
        if first:
            return (first[:157] + "…") if len(first) > 158 else first
    return f"{title} — a {category} opportunity."


def classify(title: str, description: str | None = None, hint: str | None = None) -> Classification:
    category, confidence = heuristic_category(title, description, hint)
    difficulty = heuristic_difficulty(title, description)
    summary = _heuristic_summary(title, description, category)
    result = Classification(category, difficulty, summary, confidence, "heuristic")

    if settings.llm_enabled:
        try:
            from . import llm

            upgraded = llm.classify_with_llm(title, description, category, difficulty)
            if upgraded is not None:
                cat, diff, summ = upgraded
                if cat in CATEGORIES:
                    result.category = cat
                if diff in {d.value for d in Difficulty}:
                    result.difficulty = diff
                if summ:
                    result.summary = summ
                result.method = "llm"
                result.confidence = max(result.confidence, 0.9)
        except Exception as exc:  # never let the LLM break the pipeline
            logger.warning("LLM classify failed, using heuristic: %s", exc)

    return result
