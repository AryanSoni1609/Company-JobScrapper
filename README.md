# company-career-scraper

**Scrape job postings from 169+ company career pages via Greenhouse, Lever, Ashby, and SmartRecruiters APIs — $0 cost, ~6 minute runtime, Google Sheets integration.**

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![ATS Platforms](https://img.shields.io/badge/ATS_platforms-4-orange)
![Companies](https://img.shields.io/badge/companies-169+-brightgreen)

---

## The Problem

Every company posts jobs on their own career page, but each uses a different platform — Greenhouse, Lever, Ashby, SmartRecruiters, Workday, and dozens of others. Checking them one by one is slow, inconsistent, and easy to miss. Job boards like LinkedIn and Indeed help, but they're delayed, incomplete, and heavily gamed by agencies.

Going direct to source is better — but nobody has time to check 169 career pages manually.

This tool solves that. One script queries all of them via their public APIs, filters by location and keywords, and outputs a single clean CSV — in about 6 minutes.

---

## What It Does

- Scrapes **169 company career pages** in ~6 minutes
- Finds **3,200+ relevant jobs per run** (confirmed on last run: 2026-03-29)
- Supports **4 major ATS platforms** — covers ~80% of tech and consulting companies
- Filters by **location** (Germany / remote / EMEA) and **keywords** automatically
- Company list managed via **Google Sheets** — add companies without touching code
- **Auto-detection tool** finds any company's ATS platform from just its name
- **$0 cost** — all free public APIs, no authentication, no scraping
- **0 errors, 0 blocking** — API-based, not browser-based

---

## How It Works

Each of the 4 supported ATS platforms exposes a free, unauthenticated public JSON API. This is the same API that powers their embeddable job widgets used on company websites.

The scraper:
1. Reads the company list from a Google Sheet (so you can add companies without editing code)
2. Calls the correct ATS API for each company
3. Filters results by location keywords (Germany, remote, EMEA) and role keywords
4. Deduplicates by URL across all companies
5. Outputs a single CSV ready for downstream processing

```
Google Sheet           API Calls                   Output
"Companies" tab   →    Greenhouse × N     →
(169 companies)        Lever × N          →    raw_jobs_companies.csv
active = YES           Ashby × N          →    (title, company, location,
                       SmartRecruiters × N →    description, url, source)
```

---

## Supported ATS Platforms

| ATS | API Endpoint | Returns | Coverage |
|---|---|---|---|
| **Greenhouse** | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | Full job descriptions | Most common for tech scaleups |
| **Lever** | `api.lever.co/v0/postings/{token}?mode=json` | Full job descriptions | Common for growth-stage startups |
| **Ashby** | `api.ashbyhq.com/posting-api/job-board/{token}` | Full job descriptions | Growing among AI/tech companies |
| **SmartRecruiters** | `api.smartrecruiters.com/v1/companies/{token}/postings` | Job titles + metadata | Common for large corporates |

All APIs are free, public, and require no API keys or authentication.

---

## Quick Start

### Prerequisites
- Python 3.10+
- A Google Cloud project with Sheets API enabled
- A Google service account with a downloaded JSON credentials file
- A Google Sheet shared with your service account email

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/company-career-scraper.git
cd company-career-scraper
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up environment variables

```bash
cp .env.example .env
# Edit .env and fill in your GOOGLE_SPREADSHEET_ID and GOOGLE_CREDENTIALS_PATH
```

Or export directly:

```bash
export GOOGLE_SPREADSHEET_ID=your_spreadsheet_id_here
export GOOGLE_CREDENTIALS_PATH=/path/to/google_credentials.json
```

### 4. Create the Companies tab in your Google Sheet

```bash
python setup/companies_sheet_setup.py
```

This creates a "Companies" tab with 40 starter companies across all 4 ATS platforms.

### 5. Run the scraper

```bash
python scraper/company_scraper.py
```

Output: `output/raw_jobs_companies.csv`

---

## Adding Companies

### Method 1 — Queue tab (recommended, no code needed)

1. Go to your Google Sheet → open the "Companies to be added" tab
2. Type company names in column A (one per row — just the name)
3. Run:

```bash
python setup/sheets_company_tabs.py --process
```

The script automatically detects which ATS each company uses, finds the correct board token, and routes it to the right tab. You just need the company name.

### Method 2 — Manual entry

Add a row directly to the "Companies" tab in Google Sheets:

| Column | Value | Example |
|---|---|---|
| company_name | Company name | Celonis |
| career_url | Their careers page URL | https://www.celonis.com/careers/ |
| ats_type | greenhouse / lever / ashby / smartrecruiters | greenhouse |
| board_token | Token from the ATS URL | celonis |
| category | Optional label | AI Startup |
| scope_tags | Optional tags | GenAI, BI |
| active | YES or NO | YES |
| notes | Optional | Confirmed |

Set `active = YES` and the scraper picks it up on the next run.

### Finding a board token

Go to the company's careers page and click any job listing. The URL reveals the ATS and token:

| URL pattern | ATS | Token |
|---|---|---|
| `boards.greenhouse.io/{token}/jobs/...` | Greenhouse | the part after `/boards/` |
| `job-boards.eu.greenhouse.io/{token}/...` | Greenhouse (EU) | the part after `/eu.greenhouse.io/` |
| `jobs.lever.co/{token}/...` | Lever | the part after `/lever.co/` |
| `jobs.ashbyhq.com/{token}/...` | Ashby | the part after `/ashbyhq.com/` |
| `careers.smartrecruiters.com/{token}/...` | SmartRecruiters | the part after `/smartrecruiters.com/` |

If the job opens as a popup on the company's own domain with no ATS URL visible — the ATS is unsupported (likely Workday or SuccessFactors). Set `active = NO`.

---

## ATS Auto-Detection

`ats_detector.py` finds which ATS a company uses automatically — no manual URL hunting required.

```bash
# Create a CSV with company names (one per line)
echo "Celonis
DeepL
N26
Mistral AI" > companies_to_check.csv

# Run detection
python scraper/ats_detector.py --input companies_to_check.csv
```

The detector:
- Generates ~15 token variations per company name (lowercase, CamelCase, hyphenated, suffix-stripped, etc.)
- Tests each variation against all 4 ATS APIs
- Requires at least 1 real job returned to count as a match (eliminates SmartRecruiters false positives)
- Saves results to `output/ats_detection_results.csv` immediately
- Uploads confirmed companies directly to your Google Sheet

Other flags:

```bash
python scraper/ats_detector.py --skip-sheets   # CSV output only, no Sheet upload
python scraper/ats_detector.py --recheck       # Re-check companies already in history
```

---

## Google Sheets Structure

The "Companies" tab has 8 columns:

| Column | Field | Description |
|---|---|---|
| A | company_name | e.g. "Celonis" |
| B | career_url | Company careers page (for reference) |
| C | ats_type | greenhouse / lever / ashby / smartrecruiters |
| D | board_token | Token used in the ATS API URL |
| E | category | Optional: AI Startup / Corporate / International / Consulting |
| F | scope_tags | Optional: role types this company typically hires for |
| G | active | YES = scrape this company, NO = skip |
| H | notes | Free text — verification status, quirks, etc. |

Additional tabs managed by `sheets_company_tabs.py`:

- **"Companies with no ATS"** — companies checked but no supported ATS found (~Workday/SuccessFactors)
- **"Companies to be added"** — queue tab where you write new company names

---

## Configuration

Edit the keyword lists in `scraper/company_scraper.py` to match your target roles and locations:

```python
# Role keywords — broad by design (companies are pre-filtered for relevance)
SEARCH_KEYWORDS = [
    "ai", "strategy", "digital", "transformation", "analytics", "data",
    "consultant", "operations", "product", "manager", "associate", ...
]

# Location keywords — adjust for your target country/region
GERMANY_LOCATIONS = [
    "germany", "berlin", "munich", "hamburg", "frankfurt", "remote", "emea", ...
]
```

---

## Project Structure

```
company-career-scraper/
├── README.md                          # this file
├── .env.example                       # environment variable template
├── .gitignore                         # excludes credentials and output files
├── LICENSE                            # MIT
├── requirements.txt                   # Python dependencies
│
├── scraper/
│   ├── company_scraper.py             # main scraper — reads from Google Sheet, scrapes all 4 ATS
│   └── ats_detector.py                # auto-detect ATS platform + token for any company
│
├── setup/
│   ├── companies_sheet_setup.py       # one-time Google Sheet setup (creates Companies tab)
│   └── sheets_company_tabs.py         # manage queue tab + "Companies with no ATS" tab
│
└── output/                            # generated at runtime, gitignored
    ├── raw_jobs_companies.csv         # scraper output
    ├── ats_detection_results.csv      # results from last ats_detector run
    └── ats_detection_history.csv      # permanent record of all companies checked
```

---

## API Reference

### Greenhouse

```
GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
```

Returns JSON with `jobs` array. Each job includes `title`, `location.name`, `content` (HTML description), `absolute_url`, `updated_at`. No authentication required.

EU endpoint: `https://job-boards.eu.greenhouse.io/{token}/jobs`

### Lever

```
GET https://api.lever.co/v0/postings/{token}?mode=json
```

Returns a JSON array. Each posting includes `text` (title), `categories.location`, `lists` (description sections), `hostedUrl`. No authentication required.

### Ashby

```
GET https://api.ashbyhq.com/posting-api/job-board/{token}
```

Official REST API (documented by Ashby, updated March 2025). Returns JSON with `jobs` array. Each job includes `title`, `location`, `descriptionHtml`, `jobUrl`. No authentication required.

**Note:** Tokens are case-sensitive. `DeepL` works; `deepl` does not. Always copy the token exactly from the URL at `jobs.ashbyhq.com/{token}`.

### SmartRecruiters

```
GET https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset=0
```

Returns paginated JSON with `content` array and `totalFound`. Each posting includes `name` (title), `location`, `releasedDate`. Descriptions are limited — jobs still get returned but with less text than other ATS platforms.

**Known quirk:** SmartRecruiters returns HTTP 200 with 0 jobs for any company name, even invalid ones. The detector requires at least 1 real job returned to count as a match.

---

## Known Quirks & Gotchas

These are real issues encountered while building and running this scraper across 169 companies:

| Issue | Details |
|---|---|
| **Ashby tokens are case-sensitive** | `DeepL` works, `deepl` does not. `AlephAlpha` works, `alephalpha` does not. Always copy from `jobs.ashbyhq.com/{token}` URL. |
| **Some tokens include .com suffix** | Example: a company embedding Ashby on their own domain may have token `company.com` not `company`. Check `jobs.ashbyhq.com/` if standard name fails. |
| **SmartRecruiters false positives** | Returns HTTP 200 + 0 jobs for any company name. Fixed by requiring `MIN_JOBS_REQUIRED = 1`. |
| **Some legal names differ from brand names** | Miro's Greenhouse token is `realtimeboardglobal` (legal name: RealtimeBoard). Long corporate tokens exist (e.g. `capgeminideutschlandgmbh`). |
| **Companies switch ATS** | Companies migrate between platforms. Use `ats_detector.py --recheck` periodically to catch switches. |
| **Custom popup career pages** | Some companies (e.g. Trade Republic, Zalando) open job listings as modal popups on their own domain. No ATS URL is exposed — these cannot be scraped via API. Set `active = NO`. |
| **Workday / SAP SuccessFactors** | These ATS platforms don't have public APIs. They require browser-based scraping (Playwright). Not yet implemented — see Roadmap. |
| **Greenhouse EU endpoint** | Some companies use `job-boards.eu.greenhouse.io` instead of the standard `boards-api.greenhouse.io`. The detector tries both. |
| **Duplicate tokens** | If the same company name is added twice with different casing, two rows may appear in the sheet. The scraper deduplicates by job URL so no jobs are double-counted. |

---

## Roadmap

- **Phase B — Workday / SAP SuccessFactors** (Playwright browser scraping)
  Target: up to 30 large corporates not reachable via API
- **More ATS integrations** — iCIMS, Cornerstone, Personio (if APIs become available)
- **Scheduled runs** — integration guide for n8n, GitHub Actions, cron

---

## About

Built as part of a larger job application automation pipeline. The scraper was designed to be a standalone, reusable component — anyone targeting a concentrated set of companies in a specific market can adapt the keyword and location filters for their use case.

**Author:** Babak Hasani — [linkedin.com/in/babak-hasani](https://www.linkedin.com/in/babak-hasani/)

Part of a larger pipeline: [job-automation-pipeline](https://github.com/YOUR_USERNAME/job-automation-pipeline) *(coming soon)*

---

## License

MIT — see [LICENSE](LICENSE)
