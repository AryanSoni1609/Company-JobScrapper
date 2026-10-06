# Company-JobScrapper

**Autonomous internship and job hunting: scrape company career pages, filter by an editable preferences file, tailor your resume to every job description, and get a Gmail digest at 9:00 PM IST. Runs as a CLI, a long-running daemon, or an MCP server.**

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![ATS Platforms](https://img.shields.io/badge/ATS_platforms-4-orange)
![Company source](https://img.shields.io/badge/companies-LeetCode_list_(470)_+_your_sheet-brightgreen)

---

## What it does

- **Company list:** the companies in your Google Sheet, plus every company in
  [liquidslr/leetcode-company-wise-problems](https://github.com/liquidslr/leetcode-company-wise-problems)
  (470 today). Each company's ATS is detected automatically and the company is
  appended to the sheet.
- **Scraping:** free public job-board APIs for Greenhouse, Lever, Ashby and
  SmartRecruiters. No browser automation, no API keys.
- **Filtering:** driven by `job_preference.md`, which is re-read on every scan.
  By default it keeps internships in technical roles (SDE, data, ML, ...) and
  managerial roles (project, product and program management, business analyst,
  operations, ...) in India or remote, paying around 8 LPA or more. Jobs that
  don't list pay are kept.
- **Google Sheets is append-only:** new companies, jobs and application updates
  are only ever appended. Nothing is cleared, deleted or overwritten.
- **Resume tailoring:** builds a DOCX for each job from your `resume_details.md`
  (and optionally your own Word template). Your skills and bullet points are
  re-ordered by how well they match the job description, a "Key skills for this
  role" line is added, and you get a match score. Nothing is invented: the job's
  keywords you don't have are listed in the email as suggestions instead.
- **9:00 PM IST Gmail digest:** new companies, new jobs sorted by match score
  (with pay, location and apply link), and the tailored resumes attached.
- **Autonomous:** a scheduler scans every few hours, syncs companies nightly and
  sends the digest. It runs on your PC (Windows Task Scheduler), a Linux server
  (systemd or cron) or in Docker on any cloud host.
- **MCP server:** every step is also a tool for Claude Desktop, Claude Code or
  any MCP client.

> **About auto-applying.** Greenhouse, Lever, Ashby and SmartRecruiters only
> accept applications through their APIs with the *employer's* private API
> key, so this project does **not** submit applications for you. It does
> everything up to that point: for each job, the digest has the apply link and
> the tailored resume ready to upload, and `prepare_application` /
> `mark_applied` track what you've submitted.

---

## How it works

```
LeetCode repo (470 names) ─┐                       ┌─► Google Sheet (append-only)
Google Sheet "Companies"  ─┼─► ATS detection ──────┤     Companies / Companies with no ATS
                           │                       │     Jobs / Applications
                           └─► Greenhouse/Lever/   │
                               Ashby/SmartRecruiters ─► filter (job_preference.md)
                                                         │
                               resume_details.md ───────► tailored DOCX per job
                                                         │
                                         21:00 IST ─────► Gmail digest + resumes
```

State is kept in `data/state.db` (SQLite, gitignored), so every run is
idempotent and the digest knows exactly what is new since the last email.

---

## Quick start

### 1. Create the `jobs` virtual environment

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\setup_venv.ps1
.\jobs\Scripts\Activate.ps1
```

```bash
# macOS / Linux
bash scripts/setup_venv.sh
source jobs/bin/activate
```

This installs the dependencies and copies the example files to your private,
gitignored copies: `.env`, `job_preference.md` and `resume_details.md`.

### 2. Fill in `.env`

Every key is documented in [`.env.example`](.env.example). The important ones:

| Key | What |
|---|---|
| `GOOGLE_SPREADSHEET_ID` | ID from your sheet URL `docs.google.com/spreadsheets/d/<ID>/edit` |
| `GOOGLE_CREDENTIALS_PATH` | service-account JSON key. Share the sheet with its `client_email` as Editor |
| `EMAIL_METHOD` | `gmail_api` (OAuth) or `smtp` (Gmail App Password) |
| `NOTIFY_EMAIL_TO` / `NOTIFY_EMAIL_FROM` | where the digest goes / your Gmail address |
| `GMAIL_CREDENTIALS_PATH` | OAuth "Desktop app" client JSON (for `gmail_api`) |
| `SMTP_USERNAME` / `SMTP_APP_PASSWORD` | for `smtp`: create one at https://myaccount.google.com/apppasswords |
| `DIGEST_TIME` / `TIMEZONE` | `21:00` / `Asia/Kolkata` |
| `SCAN_INTERVAL_HOURS` | how often to scan (default 6) |
| `RESUME_TEMPLATE_PATH` | optional Word template, see [templates/README.md](templates/README.md) |

<details>
<summary>Google Cloud setup (one time)</summary>

1. In https://console.cloud.google.com create a project and enable the
   **Google Sheets API**, **Google Drive API** and (for `gmail_api`) the **Gmail API**.
2. **Sheets:** IAM & Admin → Service Accounts → create one → Keys → Add key → JSON.
   Save it as `google_credentials.json` and share your sheet with the
   service account's email (Editor).
3. **Gmail (OAuth):** APIs & Services → OAuth consent screen (External, add
   yourself as a test user) → Credentials → Create OAuth client ID → *Desktop
   app*. Save it as `gmail_credentials.json`, then run:

   ```bash
   python -m jobscraper gmail-auth
   ```

   A browser opens once. The token is saved to `gmail_token.json` (gitignored)
   and refreshed automatically after that. The app only asks for permission to
   send email.
4. **Or Gmail SMTP:** set `EMAIL_METHOD=smtp` and use an App Password
   (requires 2-Step Verification).
</details>

### 3. Edit your preferences and resume details

- `job_preference.md`: job types, technical/managerial role keywords,
  excluded words, locations, minimum pay (`minimum_lpa: 8`, `tolerance_percent: 10`),
  whether to keep jobs that don't list pay, and the maximum posting age. The
  format is explained inside the file.
- `resume_details.md`: your real resume content (see
  [`resume_details.example.md`](resume_details.example.md) for the structure).

### 4. Run it

```bash
python -m jobscraper status                    # check configuration
python setup/companies_sheet_setup.py          # optional: 40 starter companies
python -m jobscraper sync-companies            # add LeetCode-list companies (60 per run)
python -m jobscraper scan                      # find jobs, tailor resumes, append to sheet
python -m jobscraper digest --dry-run          # preview the email in output/digest_preview.html
python -m jobscraper digest                    # send it now
python -m jobscraper daemon                    # run everything on schedule
```

---

## Commands

| Command | What it does |
|---|---|
| `python -m jobscraper status` | counts, last run times, active preferences |
| `python -m jobscraper sync-companies [--batch-size N \| --all]` | detect ATS for new LeetCode-list companies and append them |
| `python -m jobscraper scan [--company NAME]` | scrape, filter, tailor resumes, append new jobs |
| `python -m jobscraper tailor <job_url>` | rebuild the tailored resume for one tracked job |
| `python -m jobscraper make-template` | write a starter Word template to restyle |
| `python -m jobscraper digest [--dry-run] [--skip-if-empty]` | send (or preview) the email digest |
| `python -m jobscraper nightly` | scan, then digest (what 21:00 runs) |
| `python -m jobscraper gmail-auth` | one-time Gmail OAuth consent |
| `python -m jobscraper daemon` | run the scheduler in the foreground |
| `python -m jobscraper serve [--transport stdio\|streamable-http] [--with-scheduler]` | MCP server |

---

## MCP server

Tools: `get_status`, `get_job_preferences`, `update_job_preferences`,
`sync_companies`, `add_companies`, `scan_jobs`, `list_jobs`,
`get_job_description`, `tailor_resume`, `prepare_application`, `mark_applied`,
`send_digest`, `run_nightly`.

**Claude Desktop / Claude Code (stdio).** Add this to the client's MCP config
(adjust paths; see [`deploy/claude_mcp_config.example.json`](deploy/claude_mcp_config.example.json)):

```json
{
  "mcpServers": {
    "jobscraper": {
      "command": "D:\\Company-JobScrapper\\jobs\\Scripts\\python.exe",
      "args": ["-m", "jobscraper", "serve"],
      "cwd": "D:\\Company-JobScrapper"
    }
  }
}
```

For Claude Code you can also run
`claude mcp add jobscraper -- D:\Company-JobScrapper\jobs\Scripts\python.exe -m jobscraper serve`.

**Fully autonomous server:**
`python -m jobscraper serve --transport streamable-http --with-scheduler` serves
MCP at `http://127.0.0.1:8765/mcp` and runs the scans, company sync and
21:00 IST digest by itself. Only one scheduler runs per machine, so this is
safe next to `daemon`.

---

## Hosting: keep it running

| Where | How |
|---|---|
| **Your Windows PC** | `powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1` adds a Task Scheduler task that starts the daemon at logon with no window, wakes the PC at 20:55 for the digest, and restarts it if it crashes. Remove it with `-Uninstall`. |
| **Any terminal** | `scripts\run_daemon.ps1` / `scripts/run_daemon.sh` |
| **Linux server / VM** | `deploy/jobscraper.service` (systemd, instructions inside) or `deploy/crontab.example` |
| **Cloud (Docker)** | `docker compose up -d`. Mount `.env`, the credential JSONs and your two markdown files (see `docker-compose.yml`). Create `gmail_token.json` locally with `gmail-auth` first, then copy it to the server. |

If the machine is off at 21:00, the digest is sent as soon as the scheduler
starts again that day. Logs go to `logs/jobscraper.log`.

---

## Google Sheet tabs

| Tab | Written by | Columns |
|---|---|---|
| **Companies** | setup script, queue processor, LeetCode sync | company_name, career_url, ats_type, board_token, category, scope_tags, active, notes, job_count, detected_date |
| **Companies with no ATS** | sync / queue | same as Companies (`active = NO`) |
| **Companies to be added** | you | company_name (processed by `setup/sheets_company_tabs.py --process`, never cleared) |
| **Jobs** | `scan` | date_added, company, title, role_category, location, employment_type, salary, date_posted, ats, job_url, apply_url, match_score, matched_keywords, resume_file, status, job_id |
| **Applications** | `prepare_application`, `mark_applied` | timestamp, company, title, status, job_url, apply_url, resume_file, note |

To stop scraping a company, set `active = NO` yourself. The scraper never edits
existing rows. If a company's ATS changes, the detector reports it so you can
fix that row by hand.

---

## Project structure

```
Company-JobScrapper/
├── README.md  agents.md  skills.md        # docs (agents.md = rules for an AI operator)
├── .env.example                            # every setting, documented
├── job_preference.example.md               # → job_preference.md (yours, gitignored)
├── resume_details.example.md               # → resume_details.md (yours, gitignored)
├── requirements.txt  Dockerfile  docker-compose.yml
├── jobscraper/                             # the package (python -m jobscraper ...)
│   ├── config.py        settings from .env
│   ├── preferences.py   job_preference.md parser
│   ├── compensation.py  LPA / stipend / hourly pay → INR per year
│   ├── filters.py       job-type, role, location, pay, age checks
│   ├── ats_clients.py   Greenhouse / Lever / Ashby / SmartRecruiters fetchers
│   ├── ats_detect.py    company name → ATS + board token
│   ├── leetcode.py      LeetCode company list
│   ├── sheets.py        append-only Google Sheets helper
│   ├── state.py         SQLite state (data/state.db)
│   ├── pipeline.py      sync / scan / nightly orchestration
│   ├── resume/          parser, keyword extraction, tailoring, DOCX rendering
│   ├── notifier.py      Gmail API / SMTP
│   ├── digest.py        the 21:00 email
│   ├── scheduler.py     APScheduler jobs (Asia/Kolkata)
│   └── mcp_server.py    MCP tools
├── scraper/                                # original standalone scripts (still work)
│   ├── company_scraper.py   one-off scrape → output/raw_jobs_companies.csv
│   └── ats_detector.py      detect ATS for a CSV of names
├── setup/
│   ├── companies_sheet_setup.py   create Companies tab / append starter companies
│   └── sheets_company_tabs.py     "Companies to be added" queue + no-ATS tab
├── scripts/      setup_venv.{ps1,sh}, run_daemon.{ps1,sh}, install_windows_task.ps1
├── deploy/       systemd unit, crontab example, MCP client config example
├── templates/    README for Word templates (your template is gitignored)
├── tests/        offline unit tests: python -m unittest discover -s tests
└── data/ output/ resumes/ logs/            # runtime, gitignored (.gitkeep only)
```

---

## Supported ATS APIs

| ATS | Endpoint | Notes |
|---|---|---|
| **Greenhouse** | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | full descriptions; EU boards at `boards-api.eu.greenhouse.io` |
| **Lever** | `api.lever.co/v0/postings/{token}?mode=json` | full descriptions, `salaryRange` when published; EU at `api.eu.lever.co` |
| **Ashby** | `api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true` | tokens are case-sensitive (`DeepL`), compensation when published |
| **SmartRecruiters** | `api.smartrecruiters.com/v1/companies/{token}/postings` | descriptions fetched per posting for jobs that pass the filter |

Many large companies on the LeetCode list (Amazon, Google, Microsoft, Goldman
Sachs, ...) use Workday, SuccessFactors, iCIMS or their own career sites.
Those have no public job API, so they land in **Companies with no ATS**.

## Known quirks

| Issue | Details |
|---|---|
| Ashby tokens are case-sensitive | `DeepL` works and `deepl` does not. The fetcher tries common casings. |
| SmartRecruiters false positives | It returns HTTP 200 with 0 jobs for any name, so detection requires at least 1 job. |
| Legal vs brand names | e.g. Miro's Greenhouse token is `realtimeboardglobal`. Add such companies manually. |
| Companies switch ATS | Re-check with `python scraper/ats_detector.py --input names.csv --recheck --skip-sheets`. |
| Pay is rarely published | Unlisted pay is kept by default (`include_unknown_salary: yes`). Stipends are annualised (×12) before comparing with `minimum_lpa`. |

---

## Testing

```bash
python -m unittest discover -s tests -v
```

The tests run offline. They cover preferences, pay parsing, filtering, the
append-only sheet guarantee, resume tailoring and digest bookkeeping.

---

## Credits & license

Originally built by Babak Hasani as a standalone career-page scraper. Extended
with LeetCode-list company sync, preference-driven filtering, resume
tailoring, the Gmail digest, scheduling and the MCP server.

MIT, see [LICENSE](LICENSE).
