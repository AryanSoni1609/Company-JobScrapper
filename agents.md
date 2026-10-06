# agents.md — operating instructions for the job-scraper agent

This file tells an AI agent (Claude Code, Claude Desktop with the MCP server,
or any MCP-capable agent) what it is responsible for in this repository and
the rules it must never break. The individual capabilities it uses are
described in [skills.md](skills.md).

## Mission

Find internships (and other roles listed in `job_preference.md`) at the
companies in the Google Sheet and in the
[LeetCode company-wise list](https://github.com/liquidslr/leetcode-company-wise-problems),
keep the sheet up to date, tailor the user's resume to every new job, and
email the user a digest at **21:00 IST** every day — without the user having
to do anything.

## Hard rules (never break these)

1. **Google Sheets is append-only.** Never clear, delete, re-create, sort or
   overwrite tabs or rows. Only add a missing tab or append rows. All writes
   go through `jobscraper/sheets.py` (`AppendOnlySheets`). Status changes are
   appended to the *Applications* tab, not edited in *Jobs*.
2. **Never commit secrets or personal files.** `.env`, `*.json` credentials and
   tokens, `resume_details.md`, `job_preference.md`, `templates/resume_template.docx`,
   `data/`, `resumes/`, `logs/`, `output/` are gitignored. Run `git status`
   before every commit and make sure none of them are staged.
3. **Never invent resume content.** Tailoring only re-orders and highlights
   what is in `resume_details.md`. Keywords the user lacks are reported in the
   email as suggestions; they are not added to the resume.
4. **Never pretend to auto-apply.** Greenhouse, Lever, Ashby and SmartRecruiters
   only accept programmatic applications with the employer's private API key.
   Do not script browser form submissions, solve CAPTCHAs or create accounts.
   Prepare the application (apply link + tailored resume) and let the user submit.
5. **Respect the user's preferences file.** Filtering is driven only by
   `job_preference.md`, re-read on every scan. Do not hard-code roles,
   locations or pay thresholds in code.
6. **Be polite to job boards.** Keep the existing worker limits and retries;
   do not add aggressive parallelism or hammer an API that returns 429.
7. **Use the `jobs` virtual environment** for every command
   (`jobs\Scripts\python.exe` on Windows, `jobs/bin/python` elsewhere).

## Daily schedule (automatic)

| Time (IST) | Job | Command equivalent |
|---|---|---|
| start + 2 min, then every `SCAN_INTERVAL_HOURS` | scan all active companies | `python -m jobscraper scan` |
| 02:00 daily | detect new LeetCode companies (batch of `DETECTION_BATCH_SIZE`) until all are done, then every `COMPANY_SYNC_INTERVAL_DAYS` | `python -m jobscraper sync-companies` |
| 21:00 daily | fresh scan + Gmail digest with tailored resumes | `python -m jobscraper nightly` |

The scheduler runs inside either `python -m jobscraper daemon` or
`python -m jobscraper serve --with-scheduler`. Only one scheduler can run per
machine (a localhost port lock), so starting both is harmless.

## What the agent checks when asked to "keep the scraper running"

1. **Is the scheduler alive?**
   - Windows: `Get-ScheduledTask JobScraper` (state *Running*), or the
     `jobscraper.scheduler` lines in `logs/jobscraper.log`.
   - Linux: `systemctl status jobscraper` / `docker compose ps`.
   - If not running, start it (see "Hosting" in README.md).
2. **Did the last runs succeed?** `python -m jobscraper status` shows
   `last_scan`, `last_company_sync`, `last_digest` and pending counts.
   `last_digest` should be within the last 24 h after 21:00 IST.
3. **Read the log tail** (`logs/jobscraper.log`). Look for `ERROR`, `failed`,
   `Traceback`, `not configured`.
4. **Fix by category** (see Troubleshooting below), re-run the failed step
   once by hand, and confirm with `status`.
5. **Report** to the user only what needs them: missing credentials, an
   expired Gmail token, a sheet that is no longer shared, a broken ATS token.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Google Sheets is not configured` | `.env` missing ID or credential path | Ask the user for `GOOGLE_SPREADSHEET_ID` / service-account JSON; never guess. State keeps working locally and backlogged companies are appended on the next sync. |
| `PERMISSION_DENIED` from Sheets | sheet not shared with the service account | Ask the user to share the sheet (Editor) with the `client_email` in the JSON. |
| `No valid Gmail token` | first run or revoked consent | User runs `python -m jobscraper gmail-auth` once on a machine with a browser (or switch to `EMAIL_METHOD=smtp`). |
| `SMTPAuthenticationError` | wrong/expired App Password | User creates a new App Password. |
| Many `NOT_FOUND` for one company | company changed ATS or token | Run `python scraper/ats_detector.py --input <csv> --recheck --skip-sheets`; tell the user which row to fix by hand (rows are never edited automatically). |
| HTTP 429 / timeouts | rate limiting | Nothing; retries with back-off handle it. If persistent, raise `SCAN_INTERVAL_HOURS`. |
| 0 new jobs for days | preferences too narrow or season | Show `status` → preferences summary; suggest edits to `job_preference.md`. |
| `resume_details.md not found` | user has not provided it | Ask the user to fill `resume_details.md` (copy of the example). Scans continue without tailoring. |
| Digest missed at 21:00 | PC off/asleep | The scheduler sends a catch-up digest when it next starts the same day; the Windows task wakes the PC at 20:55. |

## Changing code

- Keep modules small and focused (`jobscraper/` package; see README map).
- Run `python -m unittest discover -s tests` before committing.
- Commit one logical change per commit with a descriptive message.
- Never add a dependency that requires an API key or paid service without
  the user's consent.
