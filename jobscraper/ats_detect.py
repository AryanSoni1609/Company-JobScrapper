"""Find which supported ATS (and board token) a company uses, from its name.

Generates likely board tokens from the name ("Goldman Sachs" -> goldmansachs,
goldman-sachs, GoldmanSachs, ...) and probes all four public job-board APIs.
A hit only counts if the board returns at least MIN_JOBS_REQUIRED jobs:
SmartRecruiters answers 200 with zero jobs for any made-up name.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .ats_clients import REQUEST_TIMEOUT, make_session

log = logging.getLogger("jobscraper.detect")

MIN_JOBS_REQUIRED = 1
PROBE_TIMEOUT = min(REQUEST_TIMEOUT, 12)

_SUFFIXES = re.compile(
    r"\s+(gmbh|ag|se|kg|bv|nv|sas|srl|ltd\.?|llc|inc\.?|corp\.?|corporation|co\.?|group|holdings?|"
    r"technologies|technology|solutions|software|labs|studios?|ai|io|hq|capital|management|"
    r"systems|networks|international|global|india)$",
    re.IGNORECASE,
)

_session = make_session()


def token_variations(company_name: str, limit: int | None = None) -> list[str]:
    """Most-likely-first list of candidate board tokens."""
    name = company_name.strip()
    out: list[str] = []

    def add(t: str):
        t = t.strip()
        if t and t not in out:
            out.append(t)

    def forms(s: str):
        lower = s.lower()
        add(re.sub(r"[^a-z0-9]", "", lower))           # goldmansachs
        add(re.sub(r"[^a-z0-9]+", "-", lower).strip("-"))  # goldman-sachs
        add(re.sub(r"[^A-Za-z0-9]", "", s))             # GoldmanSachs (Ashby is case-sensitive)
        add("".join(w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", s) if w))

    forms(name)
    stripped = name
    while True:
        new = _SUFFIXES.sub("", stripped).strip()
        if new == stripped or not new:
            break
        stripped = new
    if stripped != name:
        forms(stripped)
    if name.lower().startswith("the "):
        forms(name[4:])
    # "Apollo.io" -> apolloio + apollo ; "Booking.com" -> bookingcom + booking
    if "." in name:
        forms(name.split(".")[0])
    base = re.sub(r"[^a-z0-9]", "", stripped.lower())
    for suffix in ("inc", "hq", "careers", "jobs", "global"):
        add(base + suffix)
    return out[:limit] if limit else out


def _count_greenhouse(token: str) -> int:
    for url in (f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                f"https://boards-api.eu.greenhouse.io/v1/boards/{token}/jobs"):
        r = _session.get(url, timeout=PROBE_TIMEOUT)
        if r.status_code == 200:
            return len(r.json().get("jobs", []))
    return 0


def _count_lever(token: str) -> int:
    for url in (f"https://api.lever.co/v0/postings/{token}?mode=json",
                f"https://api.eu.lever.co/v0/postings/{token}?mode=json"):
        r = _session.get(url, timeout=PROBE_TIMEOUT)
        if r.status_code == 200 and isinstance(r.json(), list):
            return len(r.json())
    return 0


def _count_ashby(token: str) -> int:
    r = _session.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}", timeout=PROBE_TIMEOUT)
    if r.status_code == 200:
        return len(r.json().get("jobs") or [])
    return 0


def _count_smartrecruiters(token: str) -> int:
    r = _session.get(f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=1",
                     timeout=PROBE_TIMEOUT)
    if r.status_code == 200:
        return int(r.json().get("totalFound") or 0)
    return 0


PROBES = {
    "greenhouse": (_count_greenhouse, "https://boards.greenhouse.io/{token}"),
    "lever": (_count_lever, "https://jobs.lever.co/{token}"),
    "ashby": (_count_ashby, "https://jobs.ashbyhq.com/{token}"),
    "smartrecruiters": (_count_smartrecruiters, "https://careers.smartrecruiters.com/{token}"),
}


def _probe(ats: str, token: str) -> int:
    try:
        return PROBES[ats][0](token)
    except Exception:  # noqa: BLE001 — network noise means "not found here"
        return 0


def detect_ats(company_name: str, max_variations: int = 8) -> dict:
    """Return a detection result dict (active=YES when a board was found)."""
    for token in token_variations(company_name, max_variations):
        hits = []
        with ThreadPoolExecutor(max_workers=len(PROBES)) as pool:
            futures = {pool.submit(_probe, ats, token): ats for ats in PROBES}
            for fut in as_completed(futures):
                count = fut.result()
                if count >= MIN_JOBS_REQUIRED:
                    hits.append((futures[fut], count))
        if hits:
            ats, count = max(hits, key=lambda h: h[1])
            return {
                "company_name": company_name, "ats_type": ats, "board_token": token,
                "career_url": PROBES[ats][1].format(token=token), "job_count": count,
                "active": "YES", "notes": f"Auto-detected: {count} open jobs on {ats}.",
            }
    return {
        "company_name": company_name, "ats_type": "", "board_token": "", "career_url": "",
        "job_count": 0, "active": "NO",
        "notes": "No supported ATS found (likely Workday, SuccessFactors, iCIMS or a custom site).",
    }


def detect_many(names: list[str], workers: int = 6, max_variations: int = 8, progress=None) -> list[dict]:
    """Detect several companies in parallel. progress(i, total, result) is called per company."""
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(detect_ats, n, max_variations): n for n in names}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001
                res = {"company_name": futures[fut], "ats_type": "", "board_token": "", "career_url": "",
                       "job_count": 0, "active": "NO", "notes": f"Detection error: {e}"}
            results.append(res)
            if progress:
                progress(i, len(names), res)
    return results
