"""Fetch job postings from public ATS job-board APIs.

All four APIs are free and unauthenticated (the same JSON that powers the
companies' embedded job widgets). Each fetcher returns (jobs, status) where
jobs is a list of normalised dicts and status is "OK", "NOT_FOUND",
"TIMEOUT" or "ERROR: ...".

Normalised job dict keys:
    job_id, title, company, location, description, url, apply_url,
    ats, board_token, date_posted, employment_type, department,
    compensation (Compensation | None)
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .compensation import from_structured
from .preferences import Preferences

log = logging.getLogger("jobscraper.ats")

REQUEST_TIMEOUT = 30
USER_AGENT = "Company-JobScrapper/2.0 (+https://github.com/AryanSoni1609/Company-JobScrapper)"


def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",), respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
    s.headers["User-Agent"] = USER_AGENT
    return s


_session = make_session()


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)  # Greenhouse returns HTML-escaped HTML
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div|h[1-6]|ul|ol)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _job(**kw) -> dict:
    base = {
        "job_id": "", "title": "", "company": "", "location": "", "description": "",
        "url": "", "apply_url": "", "ats": "", "board_token": "", "date_posted": "",
        "employment_type": "", "department": "", "compensation": None,
    }
    base.update(kw)
    return base


def _get(urls: list[str], params: dict | None = None):
    """GET the first URL that does not 404. Returns the response or None."""
    for url in urls:
        resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        return resp
    return None


def _wrap(fetch):
    def inner(company: str, token: str, prefs: Preferences):
        try:
            return fetch(company, token, prefs)
        except requests.exceptions.Timeout:
            log.warning("Timeout fetching %s (%s)", company, fetch.__name__)
            return [], "TIMEOUT"
        except Exception as e:  # noqa: BLE001 — one bad board must not stop the scan
            log.warning("Error fetching %s (%s): %s", company, fetch.__name__, e)
            return [], f"ERROR: {e}"
    inner.__name__ = fetch.__name__
    return inner


@_wrap
def fetch_greenhouse(company: str, token: str, prefs: Preferences):
    resp = _get([f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                 f"https://boards-api.eu.greenhouse.io/v1/boards/{token}/jobs"],
                params={"content": "true"})
    if resp is None:
        return [], "NOT_FOUND"
    jobs = []
    for j in resp.json().get("jobs", []):
        depts = ", ".join(d.get("name", "") for d in j.get("departments") or [] if d.get("name"))
        jobs.append(_job(
            job_id=str(j.get("id", "")), title=j.get("title", ""), company=company,
            location=(j.get("location") or {}).get("name", ""),
            description=strip_html(j.get("content", "")),
            url=j.get("absolute_url", ""), apply_url=j.get("absolute_url", ""),
            ats="greenhouse", board_token=token,
            date_posted=(j.get("first_published") or j.get("updated_at") or "")[:10],
            department=depts,
        ))
    return jobs, "OK"


@_wrap
def fetch_lever(company: str, token: str, prefs: Preferences):
    resp = _get([f"https://api.lever.co/v0/postings/{token}",
                 f"https://api.eu.lever.co/v0/postings/{token}"], params={"mode": "json"})
    if resp is None:
        return [], "NOT_FOUND"
    jobs = []
    for j in resp.json():
        cats = j.get("categories") or {}
        loc = cats.get("location", "")
        all_locs = cats.get("allLocations") or []
        if all_locs:
            loc = ", ".join(dict.fromkeys([loc, *all_locs] if loc else all_locs))
        parts = [j.get("descriptionPlain") or strip_html(j.get("description", ""))]
        for section in j.get("lists") or []:
            parts.append(f"{section.get('text', '')}\n{strip_html(section.get('content', ''))}")
        parts.append(j.get("additionalPlain") or strip_html(j.get("additional", "")))
        created = j.get("createdAt") or 0
        date = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if created else ""
        sal = j.get("salaryRange") or {}
        comp = from_structured(sal.get("min"), sal.get("max"), sal.get("currency", ""),
                               sal.get("interval", ""), prefs) if sal else None
        jobs.append(_job(
            job_id=j.get("id", ""), title=j.get("text", ""), company=company, location=loc,
            description="\n\n".join(p for p in parts if p and p.strip()),
            url=j.get("hostedUrl", ""), apply_url=j.get("applyUrl") or j.get("hostedUrl", ""),
            ats="lever", board_token=token, date_posted=date,
            employment_type=cats.get("commitment", ""), department=cats.get("team", ""),
            compensation=comp,
        ))
    return jobs, "OK"


def _ashby_variants(token: str) -> list[str]:
    # Ashby tokens are case-sensitive (e.g. "DeepL"); try common casings.
    return list(dict.fromkeys([token, token.title().replace(" ", ""), token.lower(),
                               token.capitalize(), token.upper()]))


@_wrap
def fetch_ashby(company: str, token: str, prefs: Preferences):
    data, used = None, token
    for variant in _ashby_variants(token):
        resp = _get([f"https://api.ashbyhq.com/posting-api/job-board/{variant}"],
                    params={"includeCompensation": "true"})
        if resp is not None:
            data, used = resp.json(), variant
            break
    if data is None or data.get("jobs") is None:
        return [], "NOT_FOUND"
    if used != token:
        log.info("Ashby token '%s' worked as '%s'", token, used)
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        if j.get("isRemote") and not any("remote" in (l or "").lower() for l in locs):
            locs.append("Remote")
        comp = None
        for c in ((j.get("compensation") or {}).get("summaryComponents") or []):
            if (c.get("compensationType") or "").lower() == "salary":
                comp = from_structured(c.get("minValue"), c.get("maxValue"), c.get("currencyCode", ""),
                                       c.get("interval", ""), prefs)
                if comp:
                    break
        jobs.append(_job(
            job_id=j.get("id", ""), title=j.get("title", ""), company=company,
            location=", ".join(l for l in dict.fromkeys(locs) if l),
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")),
            url=j.get("jobUrl", ""), apply_url=j.get("applyUrl") or j.get("jobUrl", ""),
            ats="ashby", board_token=used, date_posted=(j.get("publishedAt") or "")[:10],
            employment_type=j.get("employmentType", ""), department=j.get("department", ""),
            compensation=comp,
        ))
    return jobs, "OK"


@_wrap
def fetch_smartrecruiters(company: str, token: str, prefs: Preferences):
    jobs, offset, limit = [], 0, 100
    while True:
        resp = _get([f"https://api.smartrecruiters.com/v1/companies/{token}/postings"],
                    params={"limit": limit, "offset": offset})
        if resp is None:
            return [], "NOT_FOUND"
        data = resp.json()
        postings = data.get("content") or []
        for j in postings:
            lo = j.get("location") or {}
            location = lo.get("fullLocation") or ", ".join(
                x for x in (lo.get("city", ""), lo.get("region", ""), lo.get("country", "")) if x)
            if lo.get("remote"):
                location = f"{location}, Remote" if location else "Remote"
            pid = j.get("id", "")
            url = f"https://jobs.smartrecruiters.com/{token}/{pid}"
            jobs.append(_job(
                job_id=pid, title=j.get("name", ""), company=company, location=location,
                description="",  # filled lazily by enrich_details() for jobs that pass filters
                url=url, apply_url=url, ats="smartrecruiters", board_token=token,
                date_posted=(j.get("releasedDate") or "")[:10],
                employment_type=" ".join(x for x in (
                    (j.get("typeOfEmployment") or {}).get("label", ""),
                    (j.get("experienceLevel") or {}).get("label", "")) if x),
                department=(j.get("department") or {}).get("label", ""),
            ))
        offset += limit
        if not postings or offset >= data.get("totalFound", 0):
            break
    return jobs, "OK"


def enrich_details(job: dict) -> dict:
    """Fetch the full description for ATSs whose list endpoint omits it."""
    if job.get("ats") != "smartrecruiters" or job.get("description"):
        return job
    try:
        resp = _session.get(
            f"https://api.smartrecruiters.com/v1/companies/{job['board_token']}/postings/{job['job_id']}",
            timeout=REQUEST_TIMEOUT)
        if resp.ok:
            data = resp.json()
            sections = (data.get("jobAd") or {}).get("sections") or {}
            parts = []
            for key in ("jobDescription", "qualifications", "additionalInformation"):
                sec = sections.get(key) or {}
                if sec.get("text"):
                    parts.append(f"{sec.get('title', '')}\n{strip_html(sec['text'])}".strip())
            job["description"] = "\n\n".join(parts)
            job["apply_url"] = data.get("applyUrl") or job["apply_url"]
            job["url"] = data.get("postingUrl") or job["url"]
    except requests.RequestException as e:
        log.info("Could not fetch SmartRecruiters details for %s: %s", job.get("url"), e)
    return job


ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
}


def fetch_company_jobs(company: str, ats: str, token: str, prefs: Preferences):
    fetcher = ATS_FETCHERS.get((ats or "").strip().lower())
    if fetcher is None:
        return [], f"UNSUPPORTED: {ats}"
    return fetcher(company, token, prefs)
