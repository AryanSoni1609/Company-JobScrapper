# company_scraper.py
# Scrapes job listings directly from company career pages using their ATS APIs
# and keeps only the jobs that match job_preference.md.
# Reads company list from Google Sheet "Companies" tab.
# Output: output/raw_jobs_companies.csv
#
# Supported ATS platforms (API-only, no browser needed):
#   - Greenhouse (public JSON API)
#   - Lever (public JSON API)
#   - Ashby (official public REST API)
#   - SmartRecruiters (public JSON API)
#
# Usage:
#   python scraper/company_scraper.py
#
# Filtering (job type, roles, location, minimum pay) comes from job_preference.md,
# which is re-read on every run — edit it, no code changes needed.
# For the full pipeline (append to the Jobs sheet, tailored resumes, Gmail digest)
# use:  python -m jobscraper scan
#
# Environment variables (set in .env or export before running):
#   GOOGLE_SPREADSHEET_ID   — your Google Sheet ID
#   GOOGLE_CREDENTIALS_PATH — path to your service account JSON (default: google_credentials.json)
#   OUTPUT_DIR              — where to write output CSV (default: ./output)

import csv
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from jobscraper.ats_clients import ATS_FETCHERS, enrich_details, fetch_company_jobs  # noqa: E402
from jobscraper.config import load_settings  # noqa: E402
from jobscraper.filters import evaluate, role_category  # noqa: E402
from jobscraper.preferences import load_preferences  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---------- CONFIG ----------
SETTINGS         = load_settings()
SPREADSHEET_ID   = SETTINGS.spreadsheet_id
CREDENTIALS_FILE = str(SETTINGS.google_credentials_path)
OUTPUT_DIR       = str(SETTINGS.output_dir)
OUTPUT_FILE      = os.path.join(OUTPUT_DIR, "raw_jobs_companies.csv")
SHEET_NAME       = SETTINGS.companies_tab

DELAY_BETWEEN_COMPANIES = 1  # seconds between API calls


# ---------- LOAD COMPANIES FROM GOOGLE SHEET ----------
def load_companies_from_sheet():
    """Load active companies from the Google Sheet 'Companies' tab."""
    try:
        import gspread
        gc          = gspread.service_account(filename=CREDENTIALS_FILE)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        worksheet   = spreadsheet.worksheet(SHEET_NAME)
        records     = worksheet.get_all_records()

        companies = []
        for row in records:
            if str(row.get("active", "")).strip().upper() == "YES":
                companies.append({
                    "company_name": str(row.get("company_name", "")).strip(),
                    "career_url":   str(row.get("career_url",   "")).strip(),
                    "ats_type":     str(row.get("ats_type",     "")).strip().lower(),
                    "board_token":  str(row.get("board_token",  "")).strip(),
                    "category":     str(row.get("category",     "")).strip(),
                    "scope_tags":   str(row.get("scope_tags",   "")).strip(),
                })
        return companies

    except Exception as e:
        print(f"ERROR loading companies from Google Sheet: {e}")
        print("Check that:")
        print("  1. GOOGLE_CREDENTIALS_PATH points to a valid service account JSON file")
        print("  2. GOOGLE_SPREADSHEET_ID is correct")
        print("  3. The 'Companies' tab exists (run setup/companies_sheet_setup.py first)")
        return []


# ---------- MAIN ----------
def main():
    print("=" * 60)
    print("COMPANY CAREER PAGE SCRAPER")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    prefs = load_preferences()
    print(f"\nPreferences ({prefs.source_path}):\n  {prefs.summary()}")

    print("\nLoading companies from Google Sheet...")
    companies = load_companies_from_sheet()

    if not companies:
        print("No active companies found. Exiting.")
        return

    print(f"Found {len(companies)} active companies to scrape.")

    all_jobs        = []
    success_count   = 0
    fail_count      = 0
    not_found_count = 0

    for i, company in enumerate(companies, 1):
        name        = company["company_name"]
        ats_type    = company["ats_type"]
        board_token = company["board_token"]

        if ats_type not in ATS_FETCHERS:
            print(f"\n[{i}/{len(companies)}] {name} - SKIPPED (unsupported ATS: {ats_type})")
            fail_count += 1
            continue

        print(f"\n[{i}/{len(companies)}] {name} ({ats_type})...", end=" ", flush=True)
        jobs, status = fetch_company_jobs(name, ats_type, board_token, prefs)

        if status == "OK":
            relevant = []
            for job in jobs:
                keep, _reason, comp = evaluate(job, prefs)
                if keep:
                    enrich_details(job)
                    job["salary"] = comp.display if comp else ""
                    job["role_category"] = role_category(job["title"], prefs)
                    relevant.append(job)
            print(f"found {len(relevant)} relevant jobs (of {len(jobs)})")
            all_jobs.extend(relevant)
            success_count += 1
        elif status == "NOT_FOUND":
            print(f"WARNING: board_token '{board_token}' not found on {ats_type}")
            not_found_count += 1
        else:
            print(status)
            fail_count += 1

        if i < len(companies):
            time.sleep(DELAY_BETWEEN_COMPANIES)

    # Deduplicate by URL
    seen_urls, unique_jobs = set(), []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_jobs.append(job)
        elif not url:
            unique_jobs.append(job)

    print(f"\n{'=' * 60}")
    print("RESULTS:")
    print(f"  Companies scraped successfully: {success_count}")
    print(f"  Companies with errors:          {fail_count}")
    print(f"  Board tokens not found:         {not_found_count}")
    print(f"  Total relevant jobs found:      {len(unique_jobs)}")

    fieldnames = ["title", "company", "location", "role_category", "employment_type", "salary",
                  "description", "url", "apply_url", "ats", "date_posted"]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        if unique_jobs:
            writer.writerows(unique_jobs)

    print(f"\nSaved to: {OUTPUT_FILE}")

    if not_found_count > 0:
        print(f"\nIMPORTANT: {not_found_count} companies had invalid board_tokens.")
        print("Open your Google Sheet > Companies tab and fix the board_token column")
        print("for any companies that showed 'NOT_FOUND' above.")

    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
