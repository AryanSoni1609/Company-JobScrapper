"""MCP server exposing the whole job pipeline as tools.

Run (stdio, for Claude Desktop / Claude Code / any MCP client):
    python -m jobscraper serve
Run as a network service with the scheduler inside (server / cloud):
    python -m jobscraper serve --transport streamable-http --with-scheduler

With --with-scheduler the server also performs every step by itself:
scans every few hours, syncs LeetCode companies and emails the 21:00 IST
digest — no client has to call anything.

Every tool returns a JSON-able dict; failures come back as {"error": "..."}
instead of exceptions so the calling agent can read what went wrong.
"""

from __future__ import annotations

import logging
from pathlib import Path

import anyio

from .config import load_settings, setup_logging

log = logging.getLogger("jobscraper.mcp")

INSTRUCTIONS = """\
Tools for an autonomous internship/job hunt.
Typical flow: get_status -> sync_companies (adds LeetCode-list companies) -> scan_jobs ->
list_jobs -> get_job_description / tailor_resume -> prepare_application -> mark_applied.
send_digest emails new companies + jobs + tailored resumes (runs automatically at 21:00 IST
when the scheduler is on). Google Sheets is append-only: nothing is ever cleared or overwritten.
job_preference.md controls filtering; edit it with update_job_preferences.
Applications cannot be auto-submitted on Greenhouse/Lever/Ashby/SmartRecruiters (they need the
employer's API key): prepare_application returns the apply link + tailored resume for the user.
"""


async def _call(fn, *args, **kwargs) -> dict:
    """Run blocking pipeline code in a worker thread and turn errors into data."""
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
    except Exception as e:  # noqa: BLE001
        log.exception("Tool %s failed", getattr(fn, "__name__", fn))
        return {"error": f"{type(e).__name__}: {e}"}


def build_server():
    from mcp.server.mcpserver import MCPServer

    from . import pipeline
    from .digest import send_digest as _send_digest
    from .preferences import load_preferences, parse_preferences
    from .state import State

    mcp = MCPServer(name="jobscraper", instructions=INSTRUCTIONS, version="2.0.0")

    @mcp.tool()
    async def get_status() -> dict:
        """Counts of tracked companies/jobs, pending digest items, last run times and active preferences."""
        def run():
            prefs = load_preferences()
            settings = load_settings()
            return {**State().stats(), "preferences": prefs.summary(), "preferences_file": prefs.source_path,
                    "sheets_configured": settings.sheets_configured,
                    "resume_details_present": settings.resume_details_path.is_file(),
                    "email_method": settings.email_method, "digest_time": settings.digest_time,
                    "timezone": settings.timezone}
        return await _call(run)

    @mcp.tool()
    async def get_job_preferences() -> dict:
        """Return job_preference.md (raw markdown) and how it is interpreted."""
        def run():
            prefs = load_preferences()
            return {"path": prefs.source_path, "markdown": Path(prefs.source_path).read_text(encoding="utf-8"),
                    "summary": prefs.summary()}
        return await _call(run)

    @mcp.tool()
    async def update_job_preferences(markdown: str) -> dict:
        """Replace job_preference.md with new markdown (same format). Takes effect on the next scan."""
        def run():
            prefs = parse_preferences(markdown)
            if not (prefs.job_types or prefs.role_keywords or prefs.locations):
                return {"error": "No sections recognised; keep the '## Job types' / '## Locations' format."}
            path = load_settings().job_preference_path
            path.write_text(markdown, encoding="utf-8")
            return {"saved": str(path), "summary": prefs.summary()}
        return await _call(run)

    @mcp.tool()
    async def sync_companies(batch_size: int = 60) -> dict:
        """Detect the ATS of companies from the LeetCode company-wise repo that are not in the sheet yet,
        and append them (Companies tab if a supported ATS was found, otherwise 'Companies with no ATS')."""
        return await _call(pipeline.sync_companies, batch_size=batch_size)

    @mcp.tool()
    async def add_companies(names: list[str]) -> dict:
        """Detect the ATS for specific company names and append them to the sheet."""
        return await _call(pipeline.sync_companies, names=names, batch_size=len(names) or 1, source="manual")

    @mcp.tool()
    async def scan_jobs(companies: list[str] | None = None) -> dict:
        """Scrape active companies (optionally only the given names), filter by job_preference.md,
        tailor a resume for each new job and append new jobs to the Jobs tab."""
        return await _call(pipeline.scan_jobs, company_filter=companies)

    @mcp.tool()
    async def list_jobs(only_not_emailed: bool = False, status: str | None = None, limit: int = 50) -> dict:
        """Tracked jobs, best resume match first. status: new / ready_to_apply / applied / skipped."""
        def run():
            keep = ("company", "title", "role_category", "location", "salary", "match_score", "job_url",
                    "apply_url", "resume_path", "status", "added_at", "notified_at")
            jobs = State().list_jobs(only_unnotified=only_not_emailed, status=status, limit=limit)
            return {"count": len(jobs), "jobs": [{k: j.get(k) for k in keep} for j in jobs]}
        return await _call(run)

    @mcp.tool()
    async def get_job_description(job_url: str) -> dict:
        """Full job description for a tracked job, or fetched live from a Greenhouse/Lever/Ashby/
        SmartRecruiters (or any) job URL."""
        def run():
            from .ats_clients import fetch_job_by_url
            job = State().get_job(job_url)
            if not job or not job.get("description"):
                job = fetch_job_by_url(job_url, load_preferences())
            if not job:
                return {"error": "Job not found at that URL"}
            return {k: job.get(k, "") for k in ("company", "title", "location", "employment_type", "salary",
                                                 "apply_url", "description")}
        return await _call(run)

    @mcp.tool()
    async def tailor_resume(job_url: str) -> dict:
        """Build a resume from resume_details.md keyword-matched to this job's description.
        Returns the DOCX path, match score, matched keywords and missing keywords (not added)."""
        def run():
            state = State()
            if state.get_job(job_url):
                return pipeline.tailor_existing_job(job_url)
            from .ats_clients import fetch_job_by_url
            from .resume import tailor_for_job
            job = fetch_job_by_url(job_url, load_preferences())
            if not job:
                return {"error": "Job not found at that URL"}
            t, path = tailor_for_job(job)
            return {"title": job["title"], "company": job["company"], "match_score": t.match_score,
                    "matched_keywords": t.matched_keywords, "missing_keywords": t.missing_keywords,
                    "resume_file": str(path)}
        return await _call(run)

    @mcp.tool()
    async def prepare_application(job_url: str) -> dict:
        """Get everything needed to apply: apply link + tailored resume. Marks the job ready_to_apply.
        Submission itself is manual (these ATSs reject programmatic applications without the
        employer's private API key)."""
        def run():
            state = State()
            job = state.get_job(job_url)
            if not job:
                return {"error": "Job is not tracked; run scan_jobs first or use tailor_resume with the URL."}
            if not job.get("resume_path") or not Path(job["resume_path"]).is_file():
                res = pipeline.tailor_existing_job(job_url)
                if "error" in res:
                    return res
                job["resume_path"] = res["resume_file"]
            state.set_job_status(job_url, "ready_to_apply")
            pipeline.log_application(job, "ready_to_apply")
            return {"apply_url": job.get("apply_url") or job_url, "resume_file": job["resume_path"],
                    "auto_submitted": False,
                    "next_step": "Open apply_url, upload resume_file, then call mark_applied."}
        return await _call(run)

    @mcp.tool()
    async def mark_applied(job_url: str, note: str = "") -> dict:
        """Record that the user applied (status=applied; a row is appended to the Applications tab)."""
        def run():
            state = State()
            job = state.get_job(job_url)
            if not job:
                return {"error": "Job is not tracked."}
            state.set_job_status(job_url, "applied")
            pipeline.log_application(job, "applied", note)
            return {"ok": True, "status": "applied"}
        return await _call(run)

    @mcp.tool()
    async def send_digest(dry_run: bool = False) -> dict:
        """Email the digest of new companies and jobs (with tailored resumes) now.
        dry_run=True only writes output/digest_preview.html."""
        return await _call(_send_digest, dry_run=dry_run)

    @mcp.tool()
    async def run_nightly() -> dict:
        """Exactly what the 21:00 schedule does: fresh scan, then the Gmail digest."""
        return await _call(pipeline.run_nightly)

    return mcp


def serve(transport: str | None = None, with_scheduler: bool = False, host: str | None = None,
          port: int | None = None) -> None:
    setup_logging()  # logs go to stderr + logs/, never stdout (stdio transport)
    settings = load_settings()
    transport = transport or settings.mcp_transport
    mcp = build_server()
    if with_scheduler:
        from .scheduler import start_background
        start_background()
    if transport == "stdio":
        mcp.run("stdio")
    elif transport in ("streamable-http", "http"):
        mcp.run("streamable-http", host=host or settings.mcp_host, port=port or settings.mcp_port)
    elif transport == "sse":
        mcp.run("sse", host=host or settings.mcp_host, port=port or settings.mcp_port)
    else:
        raise SystemExit(f"Unknown MCP transport {transport!r} (stdio | streamable-http | sse)")
