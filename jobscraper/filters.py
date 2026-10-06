"""Decide whether a scraped job matches job_preference.md."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .compensation import Compensation, from_text, meets_minimum
from .preferences import Preferences


@lru_cache(maxsize=4096)
def _pattern(keyword: str) -> re.Pattern:
    # whole-word match; keywords may contain spaces or punctuation ("co-op", "c++")
    return re.compile(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])")


def contains_any(text: str, keywords: list[str]) -> str | None:
    """Return the first keyword found in text (whole-word, case-insensitive)."""
    t = (text or "").lower()
    for kw in keywords:
        if kw and _pattern(kw).search(t):
            return kw
    return None


_REMOTE_WORDS = ["remote", "anywhere", "work from home", "wfh", "fully remote", "remote first"]
_REMOTE_FILLER = ["global", "globally", "worldwide", "apac", "asia", "asia pacific",
                  "hybrid", "office", "or", "and", "based", "first", "friendly", "location", "locations"]


def location_ok(location: str, prefs: Preferences) -> tuple[bool, str]:
    loc = (location or "").strip().lower()
    if not loc:
        return prefs.include_unknown_location, "no location listed"
    if not prefs.locations:
        return True, "any location"
    places = [p for p in prefs.locations if p != "remote"]
    city = contains_any(loc, places)
    if city:
        return True, city
    if "remote" in prefs.locations and contains_any(loc, _REMOTE_WORDS):
        blocked = contains_any(loc, prefs.exclude_locations)
        if blocked:
            return False, f"remote but restricted to {blocked}"
        # "San Francisco, New York, Remote" means remote within that country:
        # only accept remote postings that name no other place.
        leftover = loc
        for word in _REMOTE_WORDS + _REMOTE_FILLER:
            leftover = _pattern(word).sub(" ", leftover)
        leftover = re.sub(r"[^a-z]+", " ", leftover).strip()
        if leftover:
            return False, f"remote tied to '{leftover}'"
        return True, "remote"
    return False, f"location '{location}' not in preferences"


def _too_old(date_posted: str, prefs: Preferences) -> bool:
    if prefs.max_job_age_days <= 0 or not date_posted:
        return False
    try:
        posted = datetime.fromisoformat(date_posted[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - posted > timedelta(days=prefs.max_job_age_days)


def evaluate(job: dict, prefs: Preferences) -> tuple[bool, str, Compensation | None]:
    """Return (keep, reason, compensation) for a normalised job dict.

    The job dict comes from ats_clients and has at least: title, location,
    description, employment_type, date_posted and optionally compensation.
    """
    title = job.get("title", "")
    type_text = f"{title} {job.get('employment_type', '')}"

    if prefs.job_types and not contains_any(type_text, prefs.job_types):
        return False, "not a preferred job type", None

    excluded = contains_any(title, prefs.exclude_keywords)
    if excluded:
        return False, f"excluded keyword '{excluded}'", None

    if prefs.role_keywords:
        role_text = title
        if prefs.match_roles_in_description:
            role_text += " " + job.get("description", "")
        if not contains_any(role_text, prefs.role_keywords):
            return False, "no technical/managerial role keyword", None

    ok, why = location_ok(job.get("location", ""), prefs)
    if not ok:
        return False, why, None

    if _too_old(job.get("date_posted", ""), prefs):
        return False, f"older than {prefs.max_job_age_days} days", None

    comp = job.get("compensation") or from_text(f"{title}\n{job.get('description', '')}", prefs)
    if not meets_minimum(comp, prefs):
        if comp is None:
            return False, "pay not listed", None
        return False, f"pay below minimum ({comp.display})", comp

    return True, "matches preferences", comp


def role_category(title: str, prefs: Preferences) -> str:
    """'Technical', 'Managerial', 'Technical/Managerial' or 'Other'."""
    tech = contains_any(title, prefs.technical_roles)
    man = contains_any(title, prefs.managerial_roles)
    if tech and man:
        return "Technical/Managerial"
    return "Technical" if tech else "Managerial" if man else "Other"
