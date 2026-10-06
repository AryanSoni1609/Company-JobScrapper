"""The nightly email: new companies + new jobs + tailored resumes.

Only items not yet reported are included; they are marked as reported after
the email is sent successfully, so a failed send is retried next time.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_settings
from .state import State, now_iso

log = logging.getLogger("jobscraper.digest")

APPLY_NOTE = (
    "Greenhouse, Lever, Ashby and SmartRecruiters only accept programmatic applications with the "
    "employer's private API key, so these jobs are not auto-submitted. Each job has its tailored "
    "resume attached (or in the resumes/ folder): open the Apply link and upload it."
)


def _e(x) -> str:
    return html.escape(str(x or ""))


def build_digest(state: State | None = None) -> dict:
    settings = load_settings()
    state = state or State()
    companies = state.unnotified_companies()
    jobs = state.list_jobs(only_unnotified=True, limit=500)
    now = datetime.now(ZoneInfo(settings.timezone))
    subject = (f"Job digest {now:%d %b %Y}: {len(jobs)} new job{'s' if len(jobs) != 1 else ''}, "
               f"{len(companies)} new compan{'ies' if len(companies) != 1 else 'y'}")

    jobs.sort(key=lambda j: (-(j.get("match_score") or 0), j.get("company", "")))
    attachments = [Path(j["resume_path"]) for j in jobs if j.get("resume_path")][: settings.digest_max_attachments]

    # ── text version ──
    lines = [subject, ""]
    if companies:
        lines.append("NEW COMPANIES ADDED TO THE SHEET")
        lines += [f"- {c['company_name']} ({c['ats_type']}, {c['job_count']} open jobs)" for c in companies]
        lines.append("")
    if jobs:
        lines.append("NEW JOBS MATCHING job_preference.md")
        for j in jobs:
            lines.append(f"- [{j.get('role_category', '')}] {j['company']}: {j['title']} | {j.get('location', '')} | "
                         f"pay: {j.get('salary', 'Not listed')} | match {j.get('match_score') or 0:.0f}%")
            lines.append(f"  Apply: {j.get('apply_url') or j['job_url']}")
            if j.get("resume_path"):
                lines.append(f"  Resume: {Path(j['resume_path']).name}")
            if j.get("missing_keywords"):
                lines.append(f"  Keywords you could add (only if true): {j['missing_keywords']}")
        lines.append("")
    if not jobs and not companies:
        lines.append("No new matching jobs or companies since the last digest.")
    lines += ["", APPLY_NOTE]
    text = "\n".join(lines)

    # ── HTML version ──
    parts = [f"<h2 style='font-family:Arial'>{_e(subject)}</h2>"]
    if companies:
        parts.append("<h3 style='font-family:Arial'>New companies added to the sheet</h3><ul>")
        parts += [f"<li>{_e(c['company_name'])} &mdash; {_e(c['ats_type'])}, {_e(c['job_count'])} open jobs</li>"
                  for c in companies]
        parts.append("</ul>")
    if jobs:
        parts.append("<h3 style='font-family:Arial'>New jobs matching your preferences</h3>")
        parts.append("<table cellpadding='6' style='border-collapse:collapse;font-family:Arial;font-size:13px'>"
                     "<tr style='background:#1f3a5f;color:#fff'><th>Type</th><th>Company</th><th>Role</th>"
                     "<th>Location</th><th>Pay</th><th>Match</th><th>Apply</th><th>Resume</th></tr>")
        for i, j in enumerate(jobs):
            bg = "#f4f6f9" if i % 2 else "#ffffff"
            missing = (f"<br><small style='color:#666'>Could add (if true): {_e(j['missing_keywords'])}</small>"
                       if j.get("missing_keywords") else "")
            parts.append(
                f"<tr style='background:{bg}'><td>{_e(j.get('role_category'))}</td><td>{_e(j['company'])}</td>"
                f"<td><a href='{_e(j['job_url'])}'>{_e(j['title'])}</a>{missing}</td>"
                f"<td>{_e(j.get('location'))}</td><td>{_e(j.get('salary') or 'Not listed')}</td>"
                f"<td>{j.get('match_score') or 0:.0f}%</td>"
                f"<td><a href='{_e(j.get('apply_url') or j['job_url'])}'>Apply</a></td>"
                f"<td>{_e(Path(j['resume_path']).name) if j.get('resume_path') else '-'}</td></tr>")
        parts.append("</table>")
        if len([j for j in jobs if j.get("resume_path")]) > len(attachments):
            parts.append(f"<p style='font-family:Arial'>Only the top {len(attachments)} resumes are attached "
                         "(DIGEST_MAX_ATTACHMENTS); the rest are in the resumes/ folder.</p>")
    if not jobs and not companies:
        parts.append("<p style='font-family:Arial'>No new matching jobs or companies since the last digest.</p>")
    parts.append(f"<p style='font-family:Arial;color:#555'><small>{_e(APPLY_NOTE)}</small></p>")

    return {"subject": subject, "html": "\n".join(parts), "text": text, "attachments": attachments,
            "job_urls": [j["job_url"] for j in jobs], "company_keys": [c["name_key"] for c in companies]}


def send_digest(send_if_empty: bool = True, dry_run: bool = False) -> dict:
    from .notifier import send_email

    state = State()
    d = build_digest(state)
    summary = {"subject": d["subject"], "jobs": len(d["job_urls"]), "companies": len(d["company_keys"]),
               "attachments": [p.name for p in d["attachments"]]}
    if dry_run:
        out = load_settings().output_dir / "digest_preview.html"
        out.write_text(d["html"], encoding="utf-8")
        return {**summary, "dry_run": True, "preview": str(out)}
    if not d["job_urls"] and not d["company_keys"] and not send_if_empty:
        return {**summary, "sent": False, "reason": "nothing new"}
    result = send_email(d["subject"], d["html"], d["text"], d["attachments"])
    state.mark_jobs_notified(d["job_urls"])
    state.mark_companies_notified(d["company_keys"])
    state.set_meta("last_digest", now_iso())
    return {**summary, "sent": True, **result}
