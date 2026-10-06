# ats_detector.py
# Automatically finds which ATS platform + board token each company uses.
# Tries Greenhouse, Lever, Ashby, and SmartRecruiters APIs for each company name.
# Saves results to CSV and optionally uploads confirmed companies to Google Sheet.
#
# Usage:
#   python scraper/ats_detector.py
#   python scraper/ats_detector.py --skip-sheets
#   python scraper/ats_detector.py --input my_companies.csv
#   python scraper/ats_detector.py --recheck
#
# Input:  CSV with company names (one per line, or column "company_name")
#         Default: ./companies_to_check.csv
# Output: ./output/ats_detection_results.csv  — results from this run
#         ./output/ats_detection_history.csv  — permanent record of all companies checked
#         Google Sheet "Companies" tab        — confirmed companies (unless --skip-sheets)
#
# Environment variables:
#   GOOGLE_SPREADSHEET_ID   — your Google Sheet ID
#   GOOGLE_CREDENTIALS_PATH — path to service account JSON (default: google_credentials.json)
#   OUTPUT_DIR              — where to write output files (default: ./output)

import csv
import os
import sys
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import jobscraper.config  # noqa: E402,F401  -- loads .env into the environment

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# --- CONFIGURATION ---
SPREADSHEET_ID   = os.environ.get("GOOGLE_SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
OUTPUT_DIR       = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output"))
DEFAULT_INPUT    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "companies_to_check.csv")
RESULTS_FILE     = os.path.join(OUTPUT_DIR, "ats_detection_results.csv")
HISTORY_FILE     = os.path.join(OUTPUT_DIR, "ats_detection_history.csv")
SHEET_NAME       = "Companies"

# Minimum jobs required to count as a valid ATS match.
# SmartRecruiters returns HTTP 200 with 0 jobs for ANY company name —
# requiring at least 1 job eliminates these false positives.
MIN_JOBS_REQUIRED = 1



# Detection logic lives in jobscraper/ats_detect.py so this script, the
# queue processor and the LeetCode company sync all behave the same way.
from jobscraper import ats_detect  # noqa: E402

generate_token_variations = ats_detect.token_variations


def detect_ats(company_name):
    """
    Try all ATS platforms with token variations of the company name.
    Only counts as a match if at least MIN_JOBS_REQUIRED jobs are returned.
    Returns dict with: ats_type, board_token, career_url, job_count, active, notes
    """
    result = ats_detect.detect_ats(company_name, max_variations=20)
    if result["active"] == "YES":
        print(f"  >> FOUND: {result['ats_type']} with token '{result['board_token']}' ({result['job_count']} jobs)")
    return result


def load_input_companies(input_file):
    """Load company names from input CSV. Supports single-column or 'company_name' column."""
    companies = []

    if not os.path.exists(input_file):
        print(f"\nERROR: Input file not found: {input_file}")
        print("\nCreate a CSV file with one company name per line. Example:")
        print("  Celonis")
        print("  DeepL")
        print("  N26")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8-sig") as f:
        first_line = f.readline().strip()
        f.seek(0)

        if "," in first_line and "company_name" in first_line.lower():
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("company_name", "").strip()
                if name:
                    companies.append(name)
        else:
            for line in f:
                name = line.strip()
                if name and name.lower() != "company_name":
                    companies.append(name)

    return companies


def load_history():
    """Load previously detected companies from history file."""
    history = {}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("company_name", "").strip().lower()
                if name:
                    history[name] = row
    return history


def save_to_history(result):
    """Append a single result to the history file immediately after detection."""
    fieldnames = ["company_name", "career_url", "ats_type", "board_token",
                  "category", "scope_tags", "active", "notes", "job_count", "detected_date"]
    file_exists = os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(result)


def save_results(results):
    """Save all results from this run to the results CSV."""
    fieldnames = ["company_name", "career_url", "ats_type", "board_token",
                  "category", "scope_tags", "active", "notes", "job_count", "detected_date"]
    with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    print(f"\nResults saved to: {RESULTS_FILE}")


def upload_to_google_sheet(confirmed_companies):
    """Upload confirmed companies to Google Sheet 'Companies' tab."""
    if not confirmed_companies:
        print("\nNo confirmed companies to upload to Google Sheet.")
        return

    if not os.path.exists(CREDENTIALS_FILE):
        print(f"\nWARNING: Credentials file not found at: {CREDENTIALS_FILE}")
        print("Set GOOGLE_CREDENTIALS_PATH env var. Results saved to CSV.")
        return

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("\nWARNING: gspread not installed. Run: pip install gspread")
        return

    print(f"\nUploading {len(confirmed_companies)} confirmed companies to Google Sheet...")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        print(f"ERROR: '{SHEET_NAME}' tab not found. Run setup/companies_sheet_setup.py first.")
        return

    existing_data  = ws.get_all_records()
    existing_names = {row.get("company_name", "").strip().lower() for row in existing_data}

    new_companies = []
    ats_changed   = []

    for company in confirmed_companies:
        name_lower = company["company_name"].strip().lower()

        if name_lower in existing_names:
            # Append-only: existing rows are never modified. If the ATS changed,
            # report it so the row can be fixed by hand.
            for existing in existing_data:
                if str(existing.get("company_name", "")).strip().lower() == name_lower:
                    old_ats   = str(existing.get("ats_type",    "")).strip().lower()
                    old_token = str(existing.get("board_token", "")).strip().lower()
                    if old_ats != company["ats_type"].lower() or old_token != company["board_token"].lower():
                        ats_changed.append(company)
                        print(f"  ATS CHANGED (not modified): {company['company_name']} "
                              f"{old_ats}/{old_token} -> {company['ats_type']}/{company['board_token']}")
                    break
        else:
            new_companies.append(company)

    if new_companies:
        rows = [[
            company["company_name"], company["career_url"],
            company["ats_type"],     company["board_token"],
            "", "",  # category, scope_tags — fill manually
            "YES",
            company.get("notes", "Auto-detected by ats_detector.py"),
            company.get("job_count", ""), company.get("detected_date", ""),
        ] for company in new_companies]
        ws.append_rows(rows, value_input_option="RAW", insert_data_option="INSERT_ROWS", table_range="A1")
        for company in new_companies:
            print(f"  ADDED: {company['company_name']} ({company['ats_type']}, token: {company['board_token']})")

    print(f"\nGoogle Sheet updated (append-only):")
    print(f"  New companies appended:        {len(new_companies)}")
    print(f"  Existing rows with ATS change: {len(ats_changed)} (edit those rows by hand)")


def main():
    parser = argparse.ArgumentParser(description="ATS Detector — find company ATS platforms and tokens")
    parser.add_argument("--input",       default=DEFAULT_INPUT, help="Input CSV with company names")
    parser.add_argument("--skip-sheets", action="store_true",   help="Skip uploading to Google Sheet")
    parser.add_argument("--recheck",     action="store_true",   help="Re-check companies already in history")
    args = parser.parse_args()

    print("=" * 60)
    print("ATS DETECTOR — Auto-detect company ATS platforms and tokens")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    companies = load_input_companies(args.input)
    print(f"\nLoaded {len(companies)} companies from: {args.input}")

    history = load_history()
    if not args.recheck:
        skip_count = sum(1 for n in companies if n.strip().lower() in history)
        companies  = [n for n in companies if n.strip().lower() not in history]
        if skip_count > 0:
            print(f"Skipping {skip_count} already-detected companies (use --recheck to re-check)")

    if not companies:
        print("\nNo new companies to check. Done!")
        return

    print(f"\nChecking {len(companies)} companies...")
    print("-" * 60)

    results   = []
    confirmed = []
    not_found = []
    today     = time.strftime("%Y-%m-%d")

    for i, company_name in enumerate(companies, 1):
        print(f"\n[{i}/{len(companies)}] {company_name}")
        print(f"  Testing token variations...")

        detection = detect_ats(company_name)
        result    = {
            "company_name": company_name,
            "career_url":   detection["career_url"],
            "ats_type":     detection["ats_type"],
            "board_token":  detection["board_token"],
            "category":     "",
            "scope_tags":   "",
            "active":       detection["active"],
            "notes":        detection["notes"],
            "job_count":    detection["job_count"],
            "detected_date": today,
        }

        results.append(result)
        save_to_history(result)

        if detection["active"] == "YES":
            confirmed.append(result)
        else:
            not_found.append(company_name)

    save_results(results)

    if not args.skip_sheets:
        upload_to_google_sheet(confirmed)

    print("\n" + "=" * 60)
    print("DETECTION COMPLETE")
    print("=" * 60)
    print(f"\nTotal companies checked:     {len(results)}")
    print(f"  Confirmed (supported ATS): {len(confirmed)}")
    print(f"  Not found (unsupported):   {len(not_found)}")

    if confirmed:
        by_ats = {}
        for c in confirmed:
            by_ats.setdefault(c["ats_type"], []).append(c)
        print("\nConfirmed companies:")
        for ats, clist in sorted(by_ats.items()):
            print(f"\n  {ats.upper()} ({len(clist)}):")
            for c in clist:
                print(f"    - {c['company_name']} (token: {c['board_token']}, {c['job_count']} jobs)")

    if not_found:
        print("\nNot found (no supported ATS returned jobs):")
        for name in not_found:
            print(f"    - {name}")

    print(f"\nResults file: {RESULTS_FILE}")
    print(f"History file: {HISTORY_FILE}")


if __name__ == "__main__":
    main()
