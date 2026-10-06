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
from .sheets import COMPANY_HEADERS, AppendOnlySheets, SheetsNotConfigured
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
