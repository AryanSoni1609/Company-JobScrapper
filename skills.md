# skills.md — what the agent can do in this repository

Each skill below is one capability, with when to use it, how to run it (CLI
and MCP tool), and how to check it worked. Operating rules and the schedule
are in [agents.md](agents.md).

All CLI commands run from the repo root inside the `jobs` virtual
environment: `jobs\Scripts\python.exe -m jobscraper <command>` on Windows,
`jobs/bin/python -m jobscraper <command>` on macOS/Linux.

---

## 1. Set up the environment

**When:** first run on a new machine, or after `requirements.txt` changes.

```
powershell -ExecutionPolicy Bypass -File scripts\setup_venv.ps1   # Windows
bash scripts/setup_venv.sh                                          # macOS / Linux
```

Creates the `jobs` venv, installs dependencies and copies `.env.example`,
`job_preference.example.md`, `resume_details.example.md` to their gitignored
working copies (never overwriting existing ones).

**Check:** `python -m jobscraper status` prints JSON with `sheets_configured`.

## 2. Read and edit job preferences

**When:** the user wants different roles, locations or pay; or a scan finds
nothing for days.

- File: `job_preference.md` (format documented inside it). Re-read on every scan.
- MCP: `get_job_preferences`, `update_job_preferences(markdown)`.

**Check:** `status` → `preferences` summary shows the new values.

## 3. Sync companies from the LeetCode list

**When:** scheduled daily at 02:00; manually after the LeetCode repo adds companies.

- CLI: `sync-companies [--batch-size N | --all]`
- MCP: `sync_companies(batch_size)`, `add_companies(names)` for specific names.

Detects each new company's ATS (Greenhouse, Lever, Ashby, SmartRecruiters)
from its name, appends it to **Companies** (`active=YES`) or **Companies with
no ATS**. Already-known names are skipped. Results also live in `data/state.db`.

**Check:** output `added_with_ats`, `remaining_for_next_sync`.

## 4. Scan for jobs

**When:** scheduled every `SCAN_INTERVAL_HOURS` and right before the digest.

- CLI: `scan [--company NAME ...]`
- MCP: `scan_jobs(companies)`

Fetches every active company's postings, filters with `job_preference.md`
(job type, technical/managerial role keywords, location, minimum pay with
tolerance, posting age), tailors a resume for each new job and appends new
rows to the **Jobs** tab (deduplicated by job URL).

**Check:** `companies_scanned`, `new_matching_jobs`, `resumes_tailored`, `errors`.

## 5. Get a job description

- MCP: `get_job_description(job_url)` — works for tracked jobs and for any
  Greenhouse / Lever / Ashby / SmartRecruiters URL (plain-text fallback for others).

## 6. Tailor a resume

**When:** automatically for every new job; manually after the user updates
`resume_details.md` or for a job found elsewhere.

- CLI: `tailor <job_url>`; `make-template` for a starter Word template.
- MCP: `tailor_resume(job_url)`

Writes `resumes/<date>/<Company>_<Title>_<id>.docx` (+ `.md`). Only the
user's own content is used; `missing_keywords` are suggestions for the user.
Layout: built-in, or the user's docxtpl template (`RESUME_TEMPLATE_PATH`, see
`templates/README.md`).

**Check:** `match_score` (0–100) and that the file exists.

## 7. Prepare and track applications

- MCP: `prepare_application(job_url)` → apply link + resume, status `ready_to_apply`.
- MCP: `mark_applied(job_url, note)` → status `applied`.
- MCP: `list_jobs(only_not_emailed, status, limit)`.

Each status change is appended to the **Applications** tab. Submission is
done by the user: the supported ATSs do not allow programmatic applications
without the employer's API key.

## 8. Send the digest email

**When:** scheduled at 21:00 IST; manually to test email settings.

- CLI: `digest [--dry-run] [--skip-if-empty]`, `nightly` (scan + digest),
  `gmail-auth` (one-time OAuth consent).
- MCP: `send_digest(dry_run)`, `run_nightly()`

Contains companies added since the last digest, new jobs sorted by match
score (role type, location, pay, apply link, keywords to consider), and the
top `DIGEST_MAX_ATTACHMENTS` tailored resumes. Items are marked as reported
only after a successful send.

**Check:** `--dry-run` writes `output/digest_preview.html`; real sends return `sent: true`.

## 9. Run continuously

- Foreground: `daemon` (or `scripts/run_daemon.ps1` / `.sh`).
- Windows background + wake for 21:00: `scripts/install_windows_task.ps1`.
- Linux: `deploy/jobscraper.service` (systemd) or `deploy/crontab.example`.
- Cloud: `docker compose up -d` (MCP over HTTP at `localhost:8765/mcp` + scheduler).
- MCP client (Claude Desktop / Claude Code): `serve` over stdio; see
  `deploy/claude_mcp_config.example.json`. Add `--with-scheduler` to make the
  server run the schedule itself.

## 10. Health check

- CLI: `status`; MCP: `get_status`.
- Log: `logs/jobscraper.log`.
- Tests: `python -m unittest discover -s tests`.

## 11. Legacy scripts (still supported)

| Script | Purpose |
|---|---|
| `setup/companies_sheet_setup.py` | create the Companies tab / append the 40 starter companies |
| `setup/sheets_company_tabs.py --process` | process names typed into the "Companies to be added" tab |
| `scraper/ats_detector.py --input file.csv` | detect ATS for a CSV of names |
| `scraper/company_scraper.py` | one-off scrape to `output/raw_jobs_companies.csv` |
