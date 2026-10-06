"""Orchestration: company sync, job scan and the nightly digest.

Every function here is safe to run repeatedly (idempotent) and only ever
appends to Google Sheets. They are used by the CLI, the scheduler and the
MCP server alike.
"""

from __future__ import annotations

import logging
from datetime import date

from .ats_detect import detect_many
from .config import load_settings
from .leetcode import fetch_company_names
from .sheets import COMPANY_HEADERS, JOB_HEADERS, AppendOnlySheets, SheetsNotConfigured
from .state import State, now_iso

log = logging.getLogger("jobscraper.pipeline")


def _sheets_or_none() -> AppendOnlySheets | None:
    try:
        return AppendOnlySheets()
    except SheetsNotConfigured as e:
        log.warning("%s Continuing with local state only.", e)
        return None


def sync_companies(batch_size: int | None = None, names: list[str] | None = None,
                   source: str = "leetcode") -> dict:
    """Detect the ATS of companies not seen before and append them to the sheet.

    names: explicit company names; defaults to the LeetCode company list.
    batch_size: max companies to detect in this run (detection is slow);
                the rest are picked up by the next sync.
    """
    settings = load_settings()
    state = State()
    sheets = _sheets_or_none()

    all_names = names if names is not None else fetch_company_names()
    today = date.today().isoformat()

    def row(r: dict) -> dict:
        return {**r, "category": "LeetCode list" if r.get("source", source) == "leetcode" else source,
                "scope_tags": "", "detected_date": today}

    known = state.checked_company_keys()
    backlog_added = 0
    if sheets:
        on_sheet = sheets.company_names()
        known |= on_sheet
        # Companies detected earlier while Sheets was not configured: append them now.
        backlog = [c for c in state.companies_not_on_sheet() if c["name_key"] not in on_sheet]
        if backlog:
            sheets.append(settings.companies_tab, COMPANY_HEADERS,
                          [row(c) for c in backlog if c["active"] == "YES"])
            sheets.append(settings.no_ats_tab, COMPANY_HEADERS,
                          [row(c) for c in backlog if c["active"] != "YES"])
            backlog_added = len(backlog)
        state.mark_companies_on_sheet([c["name_key"] for c in state.companies_not_on_sheet()])
    pending = [n for n in dict.fromkeys(n.strip() for n in all_names) if n and n.lower() not in known]
    batch = pending[: batch_size or settings.detection_batch_size]
    log.info("Company sync: %d names, %d new, detecting %d this run", len(all_names), len(pending), len(batch))

    def progress(i, total, r):
        log.info("[%d/%d] %s -> %s", i, total, r["company_name"],
                 f"{r['ats_type']}:{r['board_token']} ({r['job_count']} jobs)" if r["active"] == "YES" else "no ATS")

    results = detect_many(batch, progress=progress)
    found = [r for r in results if r["active"] == "YES"]
    missing = [r for r in results if r["active"] != "YES"]

    if sheets:
        sheets.append(settings.companies_tab, COMPANY_HEADERS, [row(r) for r in found])
        sheets.append(settings.no_ats_tab, COMPANY_HEADERS, [row(r) for r in missing])
    for r in results:
        # Companies with a supported ATS are reported in the next digest.
        state.record_company(r, source, added_to_sheet=bool(sheets))

    state.set_meta("last_company_sync", now_iso())
    summary = {
        "names_in_source": len(all_names),
        "new_names": len(pending),
        "checked_this_run": len(batch),
        "added_with_ats": [f"{r['company_name']} ({r['ats_type']})" for r in found],
        "added_without_ats": len(missing),
        "remaining_for_next_sync": max(0, len(pending) - len(batch)),
        "backlog_appended_to_sheet": backlog_added,
        "sheet_updated": bool(sheets),
    }
    log.info("Company sync done: %d with ATS, %d without, %d remaining",
             len(found), len(missing), summary["remaining_for_next_sync"])
    return summary


def tailor_jobs(jobs: list[dict]) -> int:
    """Write a tailored resume for each job (sets match_score, matched_keywords,
    missing_keywords and resume_file on the dicts). Returns how many were written."""
    from .resume import load_resume, tailor_for_job

    if not jobs:
        return 0
    try:
        resume = load_resume()
    except FileNotFoundError as e:
        log.warning("Skipping resume tailoring: %s", e)
        return 0
    done = 0
    for job in jobs:
        try:
            tailored, path = tailor_for_job(job, resume)
        except Exception as e:  # noqa: BLE001 — one bad JD must not stop the scan
            log.warning("Could not tailor resume for %s: %s", job.get("url"), e)
            continue
        job["match_score"] = tailored.match_score
        job["matched_keywords"] = ", ".join(tailored.matched_keywords[:20])
        job["missing_keywords"] = ", ".join(tailored.missing_keywords[:15])
        job["resume_file"] = str(path)
        done += 1
    return done


def tailor_existing_job(job_url: str) -> dict:
    """(Re)generate the tailored resume for a job already tracked in state."""
    state = State()
    job = state.get_job(job_url)
    if not job:
        return {"error": f"Job not found in local state: {job_url}"}
    job.setdefault("url", job_url)
    if tailor_jobs([job]) == 0:
        return {"error": "Resume could not be tailored (is resume_details.md present?)"}
    state.set_job_resume(job_url, job["resume_file"])
    return {k: job[k] for k in ("title", "company", "match_score", "matched_keywords",
                                "missing_keywords", "resume_file")}


def _scan_targets(sheets: AppendOnlySheets | None, state: State) -> list[dict]:
    """Active companies from the sheet plus any detected locally but not on the sheet yet."""
    targets: dict[str, dict] = {}
    if sheets:
        for c in sheets.active_companies():
            targets[c["company_name"].lower()] = c
    for c in state.active_companies():
        targets.setdefault(c["company_name"].lower(), c)
    return list(targets.values())


def scan_jobs(company_filter: list[str] | None = None) -> dict:
    """Scrape every active company, keep jobs matching job_preference.md and
    append the new ones to the Jobs tab (de-duplicated by job URL)."""
    from concurrent.futures import ThreadPoolExecutor

    from .ats_clients import enrich_details, fetch_company_jobs
    from .filters import evaluate, role_category
    from .preferences import load_preferences

    settings = load_settings()
    state = State()
    sheets = _sheets_or_none()
    prefs = load_preferences()  # re-read every scan so edits apply immediately
    log.info("Scan with preferences from %s: %s", prefs.source_path, prefs.summary())

    companies = _scan_targets(sheets, state)
    if company_filter:
        wanted = {n.lower() for n in company_filter}
        companies = [c for c in companies if c["company_name"].lower() in wanted]
    if not companies:
        return {"error": "No active companies. Run sync-companies (or setup/companies_sheet_setup.py) first."}

    known = state.known_job_urls() | (sheets.job_urls() if sheets else set())

    def fetch(c):
        return c, fetch_company_jobs(c["company_name"], c["ats_type"], c["board_token"], prefs)

    new_jobs, errors, scanned, total_postings = [], [], 0, 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for company, (jobs, status) in pool.map(fetch, companies):
            if status != "OK":
                errors.append(f"{company['company_name']}: {status}")
                continue
            scanned += 1
            total_postings += len(jobs)
            for job in jobs:
                if not job["url"] or job["url"] in known:
                    continue
                keep, _reason, comp = evaluate(job, prefs)
                if not keep:
                    continue
                enrich_details(job)
                job["salary"] = comp.display if comp else "Not listed"
                job["role_category"] = role_category(job["title"], prefs)
                known.add(job["url"])
                new_jobs.append(job)

    tailored_count = tailor_jobs(new_jobs)

    today = date.today().isoformat()
    rows = []
    for job in new_jobs:
        job.setdefault("match_score", "")
        job.setdefault("matched_keywords", "")
        job.setdefault("resume_file", "")
        rows.append({
            "date_added": today, "company": job["company"], "title": job["title"],
            "role_category": job["role_category"], "location": job["location"],
            "employment_type": job["employment_type"], "salary": job["salary"],
            "date_posted": job["date_posted"], "ats": job["ats"], "job_url": job["url"],
            "apply_url": job["apply_url"], "match_score": job["match_score"],
            "matched_keywords": job["matched_keywords"], "resume_file": job["resume_file"],
            "status": "New - apply via link", "job_id": job["job_id"],
        })
    if sheets and rows:
        sheets.append(settings.jobs_tab, JOB_HEADERS, rows)
    for job in new_jobs:
        state.add_job(job, float(job["match_score"] or 0), job["resume_file"])

    state.set_meta("last_scan", now_iso())
    summary = {
        "companies_scanned": scanned,
        "postings_seen": total_postings,
        "new_matching_jobs": len(new_jobs),
        "resumes_tailored": tailored_count,
        "errors": errors[:25],
        "sheet_updated": bool(sheets and rows),
        "new_jobs": [f"{j['company']}: {j['title']} ({j['location']})" for j in new_jobs[:50]],
    }
    log.info("Scan done: %d companies, %d postings, %d new matching jobs, %d errors",
             scanned, total_postings, len(new_jobs), len(errors))
    return summary
