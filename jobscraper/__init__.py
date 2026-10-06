"""jobscraper — autonomous job discovery, resume tailoring and daily Gmail digest.

Modules:
    config        settings loaded from .env
    preferences   job_preference.md parser (re-read on every run)
    compensation  salary / stipend parsing and normalisation to INR per year
    filters       decide whether a job matches the preferences
    ats_clients   Greenhouse / Lever / Ashby / SmartRecruiters fetchers
    ats_detect    find which ATS + board token a company uses
    leetcode      company list from the LeetCode company-wise repo
    sheets        append-only Google Sheets helper
    state         local SQLite state (seen jobs, digest bookkeeping)
    pipeline      scan / sync / digest orchestration
    resume        resume_details.md parsing, tailoring and DOCX rendering
    notifier      Gmail API / SMTP email sending
    scheduler     APScheduler jobs (scan + 21:00 IST digest)
    mcp_server    MCP server exposing all of the above as tools
"""

__version__ = "2.0.0"
