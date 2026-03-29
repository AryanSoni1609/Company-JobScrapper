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
import re
import argparse
import requests

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

REQUEST_TIMEOUT = 10
API_DELAY       = 0.3  # seconds between API calls


def generate_token_variations(company_name):
    """
    Generate possible ATS board token variations from a company name.
    Returns a list ordered from most to least likely.
    Most ATS platforms prefer lowercase tokens; Ashby tokens are case-sensitive.
    """
    name       = company_name.strip()
    variations = []
    seen       = set()

    def add(token):
        if token and token not in seen:
            variations.append(token)
            seen.add(token)

    # Lowercase first (most likely to work for Greenhouse, Lever, SmartRecruiters)
    lower_no_spaces = re.sub(r'[^a-z0-9]', '', name.lower())
    add(lower_no_spaces)
    add(name.lower())
    add(name.lower().replace(" ", "-"))
    add(re.sub(r'[^a-z0-9\-]', '', name.lower()))

    # Original casing (needed for Ashby case-sensitive tokens)
    add(re.sub(r'\s+', '', name))   # e.g. "Aleph Alpha" -> "AlephAlpha"
    add(name)                        # e.g. "DeepL" -> "DeepL"

    # Suffix removal
    for suffix in [" GmbH", " AG", " SE", " Inc", " Inc.", " Ltd", " Ltd.",
                   " Co.", " Group", " Labs", " AI", " HQ", " IO",
                   " Invent", " Digital", " Capital"]:
        if name.lower().endswith(suffix.lower()):
            stripped = name[:len(name) - len(suffix)].strip()
            add(stripped.lower())
            add(re.sub(r'[^a-z0-9]', '', stripped.lower()))
            add(re.sub(r'\s+', '', stripped))

    # CamelCase
    words = name.split()
    if len(words) > 1:
        add("".join(w.capitalize() for w in words))

    # Common corporate token suffixes
    for corp_suffix in ["gmbh", "group", "bv", "global"]:
        add(lower_no_spaces + corp_suffix)

    # "The " prefix removal
    if name.lower().startswith("the "):
        short = name[4:]
        add(short.lower())
        add(re.sub(r'[^a-z0-9]', '', short.lower()))

    return variations


def try_greenhouse(token):
    """Returns (success, job_count, career_url) for Greenhouse."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            jobs = resp.json().get("jobs", [])
            return True, len(jobs), f"https://boards.greenhouse.io/{token}"
    except Exception:
        pass
    return False, 0, ""


def try_lever(token):
    """Returns (success, job_count, career_url) for Lever."""
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return True, len(data), f"https://jobs.lever.co/{token}"
    except Exception:
        pass
    return False, 0, ""


def try_ashby(token):
    """Returns (success, job_count, career_url) for Ashby.
    Uses the official REST API — NOT the old GraphQL endpoint.
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            jobs = data.get("jobs", [])
            return True, len(jobs), f"https://jobs.ashbyhq.com/{token}"
    except Exception:
        pass
    return False, 0, ""


def try_smartrecruiters(token):
    """Returns (success, job_count, career_url) for SmartRecruiters.
    NOTE: SR returns HTTP 200 with 0 jobs for any company name —
    MIN_JOBS_REQUIRED=1 prevents counting these as matches.
    """
    url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            jobs = resp.json().get("content", [])
            return True, len(jobs), f"https://careers.smartrecruiters.com/{token}"
    except Exception:
        pass
    return False, 0, ""


ATS_DETECTORS = {
    "greenhouse":      try_greenhouse,
    "lever":           try_lever,
    "ashby":           try_ashby,
    "smartrecruiters": try_smartrecruiters,
}


def detect_ats(company_name):
    """
    Try all ATS platforms with all token variations.
    Only counts as a match if at least MIN_JOBS_REQUIRED jobs are returned.
    Returns dict with: ats_type, board_token, career_url, job_count, active, notes
    """
    variations  = generate_token_variations(company_name)
    all_matches = []

    for token in variations:
        for ats_name, detector_fn in ATS_DETECTORS.items():
            success, job_count, career_url = detector_fn(token)
            time.sleep(API_DELAY)

            if success and job_count >= MIN_JOBS_REQUIRED:
                all_matches.append({
                    "ats_type":   ats_name,
                    "board_token": token,
                    "career_url": career_url,
                    "job_count":  job_count,
                })
                print(f"  >> FOUND: {ats_name} with token '{token}' ({job_count} jobs)")

        if all_matches:
            break  # stop trying more tokens once we have a match

    if not all_matches:
        return {
            "ats_type": "", "board_token": "", "career_url": "", "job_count": 0,
            "active": "NO",
            "notes": "No supported ATS found",
        }

    best = max(all_matches, key=lambda r: r["job_count"])
    return {
        "ats_type":    best["ats_type"],
        "board_token": best["board_token"],
        "career_url":  best["career_url"],
        "job_count":   best["job_count"],
        "active": "YES",
        "notes": f"Auto-detected. {best['job_count']} jobs found.",
    }


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

    new_companies     = []
    updated_companies = []

    for company in confirmed_companies:
        name_lower = company["company_name"].strip().lower()

        if name_lower in existing_names:
            for i, existing in enumerate(existing_data):
                if existing.get("company_name", "").strip().lower() == name_lower:
                    old_ats   = existing.get("ats_type",    "").strip().lower()
                    old_token = existing.get("board_token", "").strip().lower()
                    new_ats   = company["ats_type"].lower()
                    new_token = company["board_token"].lower()

                    if old_ats != new_ats or old_token != new_token:
                        row_num = i + 2
                        ws.update_cell(row_num, 2, company["career_url"])
                        ws.update_cell(row_num, 3, company["ats_type"])
                        ws.update_cell(row_num, 4, company["board_token"])
                        ws.update_cell(row_num, 7, "YES")
                        ws.update_cell(row_num, 8, f"ATS updated: {old_ats}/{old_token} -> {new_ats}/{new_token}")
                        updated_companies.append(company["company_name"])
                        print(f"  UPDATED: {company['company_name']} ({old_ats} -> {new_ats})")
                        time.sleep(1)
                    break
        else:
            new_companies.append(company)

    if new_companies:
        all_values = ws.get_all_values()
        next_row   = len(all_values) + 1
        for company in new_companies:
            row_data = [
                company["company_name"], company["career_url"],
                company["ats_type"],     company["board_token"],
                "", "",  # category, scope_tags — fill manually
                "YES",
                company.get("notes", "Auto-detected by ats_detector.py"),
            ]
            ws.update(f"A{next_row}:H{next_row}", [row_data])
            print(f"  ADDED: {company['company_name']} ({company['ats_type']}, token: {company['board_token']})")
            next_row += 1
            time.sleep(1)

    print(f"\nGoogle Sheet updated:")
    print(f"  New companies added:      {len(new_companies)}")
    print(f"  Existing companies updated: {len(updated_companies)}")


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
