"""Tailor a Resume to one job description.

Honest by design: nothing is invented. The tailored resume contains only the
candidate's own content, re-ordered and highlighted:
  * skills inside each category are sorted by relevance to the JD, and the
    categories with the most matches come first
  * experience / project entries and their bullet points are sorted by how
    many JD keywords they mention
  * a "Key skills for this role" line lists the JD keywords the candidate
    already has, in JD priority order (this is what ATS keyword scanners see)
  * {role} / {company} placeholders in the summary are filled in
JD keywords the candidate does not have are returned as `missing_keywords`
so the email can suggest them — they are never added to the resume.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from .keywords import ALIASES, canonical, extract_keywords, keyword_hits
from .parser import Resume

# Sections whose entries are re-ordered by relevance (education stays chronological)
_REORDER_SECTIONS = {"experience", "work experience", "internships", "projects", "leadership",
                     "positions of responsibility", "extracurriculars"}


@dataclass
class TailoredResume:
    resume: Resume
    job_title: str
    company: str
    jd_keywords: list[str]
    matched_keywords: list[str]
    missing_keywords: list[str]
    match_score: int  # 0-100: weighted share of JD keywords the resume covers
    notes: list[str] = field(default_factory=list)


def _forms(kw: str) -> list[str]:
    """The canonical keyword plus its aliases ("kubernetes" -> ["kubernetes", "k8s"])."""
    return [kw, *(alias for alias, canon in ALIASES.items() if canon == kw)]


def _has(text: str, kw: str) -> bool:
    return keyword_hits(text, _forms(kw)) > 0


def tailor_resume(resume: Resume, job: dict) -> TailoredResume:
    jd = f"{job.get('title', '')}\n{job.get('description', '')}"
    own_terms = resume.all_skills
    jd_counts = extract_keywords(jd, extra_terms=own_terms, top_n=60)
    weights = {k: c for k, c in jd_counts}
    jd_keywords = [k for k, _ in jd_counts]

    resume_text = resume.full_text
    matched = [k for k in jd_keywords if _has(resume_text, k)]
    missing = [k for k in jd_keywords if k not in matched]

    total_w = sum(weights.values()) or 1
    score = round(100 * sum(weights[k] for k in matched) / total_w) if jd_keywords else 0

    t = copy.deepcopy(resume)

    def relevance(text: str) -> float:
        return sum(weights.get(canonical(k), 0) for k in matched if _has(text, k))

    # Skills: most relevant first inside each group, and groups by relevance
    for g in t.skills:
        g.items.sort(key=lambda s: -relevance(s))
    t.skills.sort(key=lambda g: -sum(relevance(i) for i in g.items))

    for s in t.sections:
        if s.name.lower() in _REORDER_SECTIONS:
            for e in s.entries:
                e.bullets.sort(key=lambda b: -relevance(b))
            if s.name.lower() == "projects":
                s.entries.sort(key=lambda e: -relevance(e.text))
            s.bullets.sort(key=lambda b: -relevance(b))

    role = job.get("title", "").strip()
    company = job.get("company", "").strip()
    if t.summary:
        t.summary = t.summary.replace("{role}", role or "this").replace("{company}", company or "your company")
        t.summary = re.sub(r"\s+", " ", t.summary).strip()

    notes = []
    if not jd_keywords:
        notes.append("The job description had no recognisable skill keywords; resume left in original order.")
    return TailoredResume(t, role, company, jd_keywords, matched, missing, score, notes)
